#include <iostream>
using namespace std;

class Counter {
public:
    int value = 0;

    void add(int amount) {
        value += amount;
    }
};

int main() {
    Counter c;
    c.add(2);
    c.add(3);
    cout << c.value << endl;
    return 0;
}
