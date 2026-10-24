#include <stdio.h>

int main(void) {
    int x = 7;
    const char *kind;
    if (x % 2 == 0) {
        kind = "even";
    } else {
        kind = "odd";
    }
    printf("%s\n", kind);
    return 0;
}
