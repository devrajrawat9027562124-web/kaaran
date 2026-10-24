#include <stdio.h>

int main(void) {
    int x = 5;
    int *p = &x;
    *p = 10;
    printf("%d\n", x);  /* x changed, but only p was assigned */
    return 0;
}
