import re

def convert_to_vietnamese_phone_number(number):
    """
    Convert a phone number to a valid Vietnamese phone number format.

    Args:
        number (str): The phone number to convert.

    Returns:
        str: The converted phone number if valid, otherwise None.
    """
    # Remove all non-digit characters
    number = re.sub(r'\D', '', number)

    # Check if the number is valid
    if len(number) == 10 and number.startswith(('0', '1')):
        return '+84' + number[1:]
    elif len(number) == 11 and number.startswith('84'):
        return '+84' + number[2:]
    elif len(number) == 12 and number.startswith('+84'):
        return '+84' + number[3:]

    return None

def isVietnamesePhoneNumber(number):
    number = re.sub(r'^\+84', '0', number)  # Replace +84 with 0
    number = re.sub(r'^84', '0', number)    # Replace 84 with 0
    match = re.match(r"^(03|05|07|08|09|01[2|6|8|9])+([0-9]{8})$", number)
    return bool(match)

def test_isVietnamesePhoneNumber():
    valid_numbers = [
        "0912345678", "0312345678", "0512345678", "0712345678", "0812345678", "0344415562", "+84912345678", "84912345678"
    ]
    invalid_numbers = [
        "0212345678", "0412345678", "0612345678", "0112345678", "091234567", "09123456789", "abcdefghij", "1234567890"
    ]
    
    for number in valid_numbers:
        assert isVietnamesePhoneNumber(number) == True, f"Expected True for {number}"
    
    for number in invalid_numbers:
        assert isVietnamesePhoneNumber(number) == False, f"Expected False for {number}"

if __name__ == "__main__":
    test_isVietnamesePhoneNumber()