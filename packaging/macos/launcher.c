/*
 * The executable inside win-translate.app.
 *
 * It starts `python -m wintranslate` from the source checkout and stays alive
 * as its parent. That is the whole point of it: macOS attributes a child's
 * Accessibility use to the app that launched it, so the permission belongs to
 * "win-translate" rather than to Terminal or Python. It also means the Python
 * code can change (git pull) without rebuilding this binary, and a permission
 * granted to it survives such changes.
 *
 * It must spawn, not exec: after exec the process would *be* Python, and
 * macOS would check Python's identity instead of this app's.
 *
 * REPO_DIR, PYTHON and LOG_NAME are passed in by scripts/build_macos_app.py.
 */

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static volatile pid_t child = 0;

/* Quit from Activity Monitor, logout and shutdown all signal this process;
 * pass it on so the app underneath gets to shut down too. */
static void forward(int sig) {
    if (child > 0) {
        kill(child, sig);
    }
}

/* Launched from Finder, stdout and stderr go nowhere. Send them to the same
 * log start.command writes, so a failed start leaves a trace. */
static void redirect_output(void) {
    const char *home = getenv("HOME");
    if (home == NULL) {
        return;
    }
    char path[4096];
    int written = snprintf(path, sizeof path, "%s/Library/Logs/%s", home, LOG_NAME);
    if (written < 0 || (size_t)written >= sizeof path) {
        return;
    }
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd < 0) {
        return;
    }
    dup2(fd, STDOUT_FILENO);
    dup2(fd, STDERR_FILENO);
    close(fd);
}

int main(void) {
    redirect_output();

    if (chdir(REPO_DIR) != 0) {
        fprintf(stderr, "win-translate: cannot enter %s: %s\n", REPO_DIR, strerror(errno));
        return 1;
    }

    struct sigaction action;
    memset(&action, 0, sizeof action);
    action.sa_handler = forward;
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGHUP, &action, NULL);

    char *argv[] = {PYTHON, "-m", "wintranslate", NULL};
    pid_t pid;
    int rc = posix_spawn(&pid, PYTHON, NULL, NULL, argv, environ);
    if (rc != 0) {
        fprintf(stderr, "win-translate: cannot start %s: %s\n", PYTHON, strerror(rc));
        return 1;
    }
    child = pid;

    int status;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno != EINTR) {
            fprintf(stderr, "win-translate: waitpid: %s\n", strerror(errno));
            return 1;
        }
    }
    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);
    }
    return 128 + WTERMSIG(status);
}
