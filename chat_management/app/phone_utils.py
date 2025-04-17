import re
import phonenumbers
import logging

logger = logging.getLogger(__name__)

def is_phone_number(number):
    try:
        parsed_phone = phonenumbers.parse(number, None)
        if not phonenumbers.is_valid_number(parsed_phone):
            logger.error(f"Invalid phone number: {number}")
            return False
        return True
    except Exception as e:
        print(e)
        return False


def format_phone_number(number):
    parsed_phone = phonenumbers.parse(number, None)
    return phonenumbers.format_number(parsed_phone, phonenumbers.PhoneNumberFormat.E164)

def test_isVietnamesePhoneNumber():
    valid_numbers = [
        "0912345678", "0312345678", "0512345678", "0712345678", "0812345678", "0344415562", "+84912345678", "84912345678"
    ]
    invalid_numbers = [
        "0212345678", "0412345678", "0612345678", "0112345678", "091234567", "09123456789", "abcdefghij", "1234567890"
    ]
    
    for number in valid_numbers:
        assert is_phone_number(number) == True, f"Expected True for {number}"
    
    for number in invalid_numbers:
        assert is_phone_number(number) == False, f"Expected False for {number}"

if __name__ == "__main__":
    test_isVietnamesePhoneNumber()