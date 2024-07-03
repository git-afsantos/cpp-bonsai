// SPDX-License-Identifier: MIT
// Copyright © 2024 André Santos

using namespace std;

int main ()
{
    int x, y, z;
    bool a, b;
    x = 10;
    y = 4;
    x = y;
    z = 7;

    y = 2 + (x = 5);
    x = y = z = 5;

    x = 11 - 3;
    x = x * 3;
    x = x / 3;
    x = x % 3;

    y += x;
    x -= 5;
    x *= y;
    y /= x;
    x %= 2;
    x >>= 3;
    y <<= 4;
    x &= 30;
    x |= 16;
    y ^= 20;

    ++x;
    y++;
    --x;
    y--;

    a = x == y;
    b = x != z;
    a = x > y;
    b = !(z < x);
    a = x >= z && x < 1;
    b = z <= y || x == 0;

    z = a ? 1 : 0;

    x = (y=3, y+2);

    x = x & 100;
    x = x | 24;
    x = x ^ 316;
    x = ~x;
    y = z << 2;
    y = y >> 1;

    z = (int) 3.14;

    return x + y * z;
}