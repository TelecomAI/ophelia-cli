def approval_listener():
    answer = input("Do you approve? (yes/no): ")

    if answer == "yes":
        return True
    else:
        return False

# Test the listener independently before integrating it into OPHELIA
if __name__ == "__main__":
    result = approval_listener()
    print("Permission granted:", result)