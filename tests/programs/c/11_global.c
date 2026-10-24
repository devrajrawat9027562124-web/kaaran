#include <stdio.h>

int count = 0;

void tick(void) {
    count++;
}

int main(void) {
    tick();
    tick();
    printf("%d\n", count);
    return 0;
}
