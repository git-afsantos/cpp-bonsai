// SPDX-License-Identifier: MIT
// Copyright © 2024 André Santos

int f() { return 4; }

double g(double x) { return x * 10; }

double h(double x, double (*y)(double)) { return f() + ::g(x) * y(x); }

namespace N {
    int f() { return ::f(); }

    double g(double x) { return ::g(x * x); }

    double h(double x, double (*y)(double)) { return f() + N::g(x) * y(x); }
}

class C {
public:
    int x_;
    C(): x_(1) {}
    int m(int a) { return x_ * this->x_ * a; }
};


int main(int argc, char ** argv) {
    C c;
    c.m(42);

    int a = f();
    a = g(a);
    a = h(a, g);

    int b = N::f();
    b = N::g(a);
    b = N::h(a, N::g);

    return 0;
}