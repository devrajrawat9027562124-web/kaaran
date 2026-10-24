#include <stdio.h>
#include <stdlib.h>

struct Node {
    int data;
    struct Node *left;
    struct Node *right;
};

struct Node *insert(struct Node *root, int value) {
    if (root == NULL) {
        struct Node *node = malloc(sizeof(struct Node));
        node->data = value;
        node->left = NULL;
        node->right = NULL;
        return node;
    }
    if (value < root->data)
        root->left = insert(root->left, value);
    else
        root->right = insert(root->right, value);
    return root;
}

int main(void) {
    struct Node *root = NULL;
    root = insert(root, 50);
    root = insert(root, 30);
    root = insert(root, 70);
    struct Node *old = root->left;
    root->left = NULL;
    free(old);
    printf("%d\n", root->data);
    return 0;
}
