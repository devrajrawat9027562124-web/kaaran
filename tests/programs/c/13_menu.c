#include <stdio.h>

int main(void) {
    int choice, total = 0, value;
    while (1) {
        printf("1. Add  2. Show  3. Exit\n");
        if (scanf("%d", &choice) != 1) {
            while (getchar() != '\n');
            continue;
        }
        switch (choice) {
            case 1:
                scanf("%d", &value);
                total += value;
                break;
            case 2:
                printf("Total: %d\n", total);
                break;
            case 3:
                return 0;
            default:
                printf("Invalid choice\n");
        }
    }
}
