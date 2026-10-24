#include <stdio.h>

int main(void) {
    int x = 1;
    int y = 2;
    int *p = &x;
    *p = 5;
    y = y + 1;
    printf("%d %d\n", x, y);
    return 0;
}
