#include <iostream>
#include <vector>
using namespace std;

int main() {
    vector<int> v;
    for (int i = 1; i <= 3; i++) {
        v.push_back(i * i);
    }
    int sum = 0;
    for (int x : v) {
        sum += x;
    }
    cout << sum << endl;
    return 0;
}
