#include <stdio.h>

void swap(int *a, int *b) {
    int t = *a;
    *a = *b;
    *b = t;
}

int main(void) {
    int x = 1, y = 2, z = 3;
    swap(&x, &y);
    printf("%d\n", x);
    return 0;
}
