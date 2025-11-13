from main import greet, Calculator


def example_greet_usage():
    message = greet("Alice")
    print(message)
    
    # Multiple uses
    greet("Bob")
    greet("Charlie")
    
    return message


def example_calculator_usage():
    calc = Calculator()
    
    result_add = calc.add(5, 3)
    print(f"Addition: {result_add}")
    
    result_multiply = calc.multiply(4, 7)
    print(f"Multiplication: {result_multiply}")
    
    calc.add(10, 20)
    calc.multiply(6, 8)
    
    return calc


def main():
    example_greet_usage()
    example_calculator_usage()
    
    print(greet("World"))
    
    calculator = Calculator()
    calculator.add(1, 2)
    calculator.multiply(3, 4)


if __name__ == "__main__":
    main()
