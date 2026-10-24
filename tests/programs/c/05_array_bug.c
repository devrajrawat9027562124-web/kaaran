#include <stdio.h>

int main(void) {
    int marks[3] = {80, 90, 70};
    int total = 0;
    for (int i = 1; i < 3; i++) {
        total += marks[i];
    }
    printf("%d\n", total / 3);  /* expected 80 */
    return 0;
}
