class Vector; // forward declaration
 
class Matrix
{
    // ...
    friend Vector operator*(const Matrix&, const Vector&);
};
 
class Vector
{
    // ...
    friend Vector operator*(const Matrix&, const Vector&);
};


class S
{
    int d1;             // non-static data member
    int a[10] = {1, 2}; // non-static data member with initializer (C++11)
 
    static const int d2 = 1; // static data member with initializer
 
    virtual void f1(int) = 0; // pure virtual member function
 
    std::string d3, *d4, f2(int); // two data members and a member function
 
    enum { NORTH, SOUTH, EAST, WEST };
 
    struct NestedS
    {
        std::string s;
    } d5, *d6;
 
    typedef NestedS value_type, *pointer_type;
};


class M
{
    std::size_t C;
    std::vector<int> data;
public:
    M(std::size_t R, std::size_t C) : C(C), data(R*C) {} // constructor definition
 
    int operator()(std::size_t r, std::size_t c) const // member function definition
    {
        return data[r * C + c];
    }
 
    int& operator()(std::size_t r, std::size_t c) // another member function definition
    {
        return data[r * C + c];
    }
};


class C
{
public:
    C();          // public constructor
    C(const S&);  // public copy constructor
    virtual ~C(); // public virtual destructor
private:
    int* ptr; // private data member
};


class Base
{
protected:
    int d;
};
 
class Derived : public Base
{
public:
    using Base::d;    // make Base's protected member d a public member of Derived
    using Base::Base; // inherit all bases' constructors (C++11)
};


struct N
{
    template<typename T>
    void f(T&& n);
 
    template<class CharT>
    struct NestedN
    {
        std::basic_string<CharT> s;
    };
};


template<typename T>
struct Foo
{
    static_assert(std::is_floating_point<T>::value, "Foo<T>: T must be floating point");
    using type = T;  // alias declarations
};
