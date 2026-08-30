"""nums=list(map(int,input("n:").split()))
k=int(input("enter the k"))
for i in range(len(nums)-1):
    for j in range(i,len(nums)):
        if k==sum(nums[i:j+1]):
            print(nums[i:j+1])
"""

#wap to print plaindrone from from a given subarray:
"""nums=list(map(int,input("enternumber:").split()))
for i in range(len(nums)):
    for j in range(i,len(nums)):
        subarray=nums[i:j+1]
        if subarray==subarray[::-1] and len(subarray)>1:
            print(subarray)"""

#wap to to print longest plandromic subarray:
"""nums=list(map(int,input("enter:").split()))
res=[]
for i in range(len(nums)):
    for j in range(i,len(nums)):
        subarray=nums[i:j+1]
        if subarray==subarray[::-1] and len(subarray)>len(res):
            res=subarray
print(res)

#maximum occurance of a subarray:
nums=list(map(int,input("enternumber:").split()))
sub={}
for i in range(len(nums)):
    for j in range(i,len(nums)):
        subarray=tuple(nums[i:j+1])
        if len(subarray)>1:
            if subarray in sub :
                sub[subarray]+=1
            else:
                sub[subarray]=1
max_sub=(max(sub,key=sub.get))
print(list(max_sub))
print(sub[max_sub])

#wap the given number is even or odd.


def even_odd(n):
    return 'even' if n%2==0 else 'odd'

print(even_odd(5))


#wap to print the series of number upto n:
def series(n):
    for i in range(n):
        print(i)
(series(4))
"""

#wap to check the given number is prime or not:

def is_prime(num):
    if num==1 or num==0:
        return False
    if num==2:
        return True
    for i in range(3,int(num**.5)+1):
        if num%i==0:
            return False
    return True
print(is_prime(37))
print(is_prime(57))
print(is_prime(27))


#wap which reverse the given string:
def reverse(s):
    return s[::-1]