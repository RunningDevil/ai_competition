def bubble_sort(numbers):
    arr = numbers[:]
    for i in range(len(arr) - 1):
        for j in range(len(arr) - 1 - i):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr


if __name__ == "__main__":
    data = [5, 1, 4, 2, 8]
    result = bubble_sort(data)
    print("original:", data)
    print("sorted:", result)
