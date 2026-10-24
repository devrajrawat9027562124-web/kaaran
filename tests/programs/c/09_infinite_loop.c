#include <stdio.h>

int main(void) {
    int i = 0;
    while (i < 5) {
        printf("%d\n", i);
        /* bug: i is never increased */
    }
    return 0;
}
