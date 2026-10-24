#include <stdio.h>

int square(int n) {
    int result = n * n;
    return result;
}

int main(void) {
    int a = square(4);
    printf("%d\n", a);
    return 0;
}
