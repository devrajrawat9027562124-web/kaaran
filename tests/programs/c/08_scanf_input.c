#include <stdio.h>

int main(void) {
    int age;
    printf("Age: ");
    scanf("%d", &age);
    printf("Next year you will be %d\n", age + 1);
    return 0;
}
