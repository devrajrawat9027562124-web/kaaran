#include <stdio.h>

int main(void) {
    int *p = NULL;
    printf("before\n");
    *p = 1;
    printf("never printed\n");
    return 0;
}
