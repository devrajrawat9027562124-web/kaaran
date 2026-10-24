"""Check the Docker sandbox end to end (CI runs this after building the image).

    docker build -t kaaran-runner backend/runner
    python backend/sandbox_check.py

It traces a C and a C++ program in the real container, then runs a program
that tries to write outside /tmp and to open a network connection: both
must fail.
"""
import os
import sys
import time

os.environ.setdefault("KAARAN_SANDBOX", "docker")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sandbox  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ESCAPE = r"""#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

int main(void) {
    FILE *f = fopen("/etc/kaaran-test", "w");
    printf("write:%s\n", f ? "yes" : "no");
    int s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons(80);
    inet_pton(AF_INET, "1.1.1.1", &a.sin_addr);
    printf("net:%s\n", connect(s, (struct sockaddr *)&a, sizeof a) == 0 ? "yes" : "no");
    return 0;
}
"""


def program(path):
    with open(os.path.join(ROOT, "tests", "programs", path), encoding="utf-8") as f:
        return f.read()


def check(name, condition, detail):
    print(f"{'ok  ' if condition else 'FAIL'} {name}: {detail}")
    return condition


def main():
    results = []
    start = time.time()
    t = sandbox.run_trace("c", program("c/07_pointer_alias.c"))
    results.append(check("C trace", t["error"] is None and t["stdout"] == "10\n",
                         f"{len(t['steps'])} steps, stdout={t['stdout']!r}, error={t['error']!r}, "
                         f"{time.time() - start:.1f}s"))

    start = time.time()
    t = sandbox.run_trace("cpp", program("cpp/02_vector.cpp"))
    last = t["steps"][-1]["locals"] if t["steps"] else {}
    results.append(check("C++ trace", t["stdout"] == "14\n" and last.get("v") == "{1, 4, 9}",
                         f"{len(t['steps'])} steps, v={last.get('v')!r}, {time.time() - start:.1f}s"))

    start = time.time()
    t = sandbox.run_trace("c", program("c/09_infinite_loop.c"))
    results.append(check("Endless loop stops", t["truncated"],
                         f"{len(t['steps'])} steps, error={t['error']!r}, {time.time() - start:.1f}s"))

    t = sandbox.run_trace("c", ESCAPE)
    results.append(check("No writing outside /tmp", "write:no" in t["stdout"], repr(t["stdout"])))
    results.append(check("No network", "net:no" in t["stdout"], repr(t["stdout"])))

    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
