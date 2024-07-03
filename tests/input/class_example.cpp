// SPDX-License-Identifier: MIT
// Copyright © 2024 André Santos

#include <new>
#define SOME_VALUE 0

class C;

class C {
public:
    C();
    void m(int a);
private:
    int x_;
};

C::C(void) : x_(SOME_VALUE) {}

void C::m(int a) {
    a = (a + 2) * 3;
    x_ = a;
}

int main(int argc, char ** argv) {
    C c;
    c.m(42);

    C * c1 = new C;
    C * c2 = new (std::nothrow) C;
    new (c2) C;

    delete c1;
    delete c2;

    return 0;
}