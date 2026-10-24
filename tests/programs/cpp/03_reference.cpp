#include <iostream>
using namespace std;

void addOne(int &n) {
    n = n + 1;
}

int main() {
    int a = 5;
    addOne(a);
    cout << a << endl;
    return 0;
}
