#include <stdio.h>

int main(void) {
    int a[4] = {3, 1, 4, 1};
    int max = a[0];
    int checks = 0;
    for (int i = 1; i < 4; i++) {
        if (a[i] > max) {
            max = a[i];
        }
        checks++;
    }
    printf("%d\n", max);
    return 0;
}
