"""Expression corpus: collection, numeric and conversion functions."""

from __future__ import annotations


def _lines(block: str) -> list[str]:
    return [ln for ln in block.strip().split("\n") if ln.strip()]


def collection_exprs() -> list[str]:
    return _lines(r'''
length([1,2,3])
length([])
length({})
length({a=1,b=2})
length("abc")
length("")
length("héllo")
length("👨‍👩‍👧")
length("á")
length("🇺🇸🇫🇷")
length(toset([1,1,2]))
length(tolist([1]))
length(1)
length(true)
length(null)
length(["a",["b","c"]])
length(tomap({a=1}))
length("\r\n")
concat([1], [2,3])
concat([], [])
concat([1])
concat()
concat([1], "a")
concat([1], null)
concat(["a"], [1])
concat(["a"], [[1]])
concat([[1]], [[2,3]])
concat(tolist([1]), tolist([2]))
concat(tolist([1]), tolist(["a"]))
concat(tolist([1]), [2])
concat([1], tolist([2]))
concat(toset([1]), [2])
concat([{a=1}], [{b=2}])
concat(tolist([{a=1}]), tolist([{a=2}]))
concat([null], [1])
concat([1,2], [3], [4,5,6])
concat("a", "b")
concat({a=1}, [1])
contains([1,2,3], 2)
contains([1,2,3], 4)
contains([1,2,3], "2")
contains(["a","b"], "a")
contains(["a","b"], 1)
contains([], "a")
contains(toset(["a"]), "a")
contains([1,2,3], [1])
contains([[1],[2]], [1])
contains([{a=1}], {a=1})
contains([null], null)
contains(["a"], null)
contains({a=1}, "a")
contains("abc", "a")
contains([1,2], 2.0)
contains([true], true)
contains([true], "true")
contains(["1"], 1)
contains(null, 1)
contains([1.5], 1.5)
distinct([1,2,2,3,1])
distinct([])
distinct(["a","b","a"])
distinct([1,"1"])
distinct([1,"1",true])
distinct([[1],[1],[2]])
distinct([{a=1},{a=1}])
distinct(toset([1,2]))
distinct(tolist([1,1]))
distinct([null,null])
distinct([1,1.0])
distinct(["b","a","b"])
distinct("a")
distinct(null)
distinct({a=1})
element([1,2,3], 0)
element([1,2,3], 3)
element([1,2,3], 4)
element([1,2,3], -1)
element([1,2,3], -4)
element([1,2,3], 100)
element([1,2,3], 1.5)
element([1,2,3], "1")
element([], 0)
element(["a","b"], 1)
element(toset(["b","a"]), 0)
element(toset(["b","a"]), 2)
element(tolist(["x"]), 5)
element([1,"a"], 1)
element({a=1}, 0)
element("abc", 0)
element(null, 0)
element([1], null)
element([[1],[2]], 1)
element([1,2,3], 3.0)
element([1,2,3], 1e0)
element([1,2,3], 99999999999999999999)
element([1,2,3], -99999999999999999999)
flatten([1,[2,3],[[4]]])
flatten([])
flatten([[],[]])
flatten([1,2])
flatten([[1,2],[3]])
flatten([["a"],["b",["c"]]])
flatten([{a=1},[{b=2}]])
flatten([[1],"a"])
flatten([toset([1,2]), [3]])
flatten(toset([1]))
flatten(tolist([[1],[2]]))
flatten([null])
flatten([[null]])
flatten("a")
flatten(null)
flatten({a=[1]})
flatten([1,[2]])[1]
flatten([[[[1]]]])
flatten([tolist([1]), tolist([2])])
index([1,2,3], 2)
index([1,2,3], 4)
index(["a","b","a"], "a")
index(["a","b"], "b")
index([1,2,3], "2")
index([], 1)
index(["1"], 1)
index([[1],[2]], [2])
index(toset(["a","b"]), "b")
index(tolist(["a"]), "a")
index([null], null)
index("abc", "a")
index(null, 1)
index([1,2], 2.0)
index([{a=1}], {a=1})
keys({b=1,a=2})
keys({})
keys(tomap({b=1,a=2}))
keys({"B"=1,"a"=2,"A"=3})
keys({"é"=1,"e"=2,"z"=3})
keys([1])
keys(null)
keys("a")
keys({a=null})
values({b=1,a=2})
values({})
values(tomap({b=1,a=2}))
values({a=1,b="x"})
values({a=[1],b=[2]})
values({a={x=1},b={y=2}})
values(tomap({a="x"}))
values(tomap({a=[1]}))
values([1])
values(null)
values({b=1,a=[1]})
lookup({a=1}, "a")
lookup({a=1}, "b")
lookup({a=1}, "b", 2)
lookup({a=1}, "b", "x")
lookup({a=1}, "a", "x")
lookup({a="x"}, "b", "y")
lookup({a="x"}, "b", 1)
lookup({a=null}, "a", "d")
lookup({a=null}, "a")
lookup({}, "a", null)
lookup({}, "a")
lookup(tomap({a=1}), "b", 3)
lookup(tomap({a=1}), "b", "x")
lookup(tomap({a="x"}), "b")
lookup({a=[1]}, "a")
lookup({a=[1]}, "b", [2])
lookup({a={x=1}}, "a")
lookup({a=1}, 1, 2)
lookup({"1"=1}, 1)
lookup({"1"=1}, 1, 2)
lookup({a=1}, null, 2)
lookup({a=1}, "a", null)
lookup([1], 0, 2)
lookup([1], 0)
lookup(null, "a", 1)
lookup({a=1}, "b", {})
lookup({a=1}, ["a"], 1)
lookup({a={b=1}}, "b", "d")
lookup(tomap({a={b=1}}), "c", {b=2})
lookup(tomap({a=[1]}), "c", ["x"])
lookup({a=1,b="x"}, "z", true)
merge({a=1}, {b=2})
merge({a=1}, {a=2})
merge({a=1}, null)
merge(null, {a=1})
merge(null)
merge({a=1}, {})
merge()
merge({})
merge({a={x=1}}, {a={y=2}})
merge({a=[1]}, {a=[2]})
merge({a=1}, {b="x"})
merge(tomap({a=1}), tomap({b=2}))
merge(tomap({a=1}), tomap({b="x"}))
merge(tomap({a=1}), {b="x"})
merge(tomap({a=1}), {b=2})
merge({a=1}, tomap({b=2}))
merge(tomap({a=[1]}), tomap({b=[2]}))
merge(tomap({a=[1]}), tomap({b=["x"]}))
merge(tomap({a={x=1}}), tomap({b={x=2}}))
merge(tomap({a={x=1}}), tomap({b={y=2}}))
merge({a=1}, [1])
merge({a=1}, "x")
merge([{a=1}])
merge({a=1}, {b=null})
merge({a=null}, {a=1})
merge({a=1}, {a=null})
merge({a=1,b=2}, {b=3,c=4}, {c=5,d=6})
merge({"é"=1}, {"e"=2})
merge({a=1}, null, {b=2})
merge(null, null)
merge(tomap({}), tomap({}))
merge(tomap({}), {a=1})
merge({}, {})
range(3)
range(1, 4)
range(1, 10, 3)
range(10, 0, -3)
range(0)
range(-3)
range(3, 0)
range(0, 1, 0.25)
range(0, 0.5, 0.1)
range(1, 4, 0)
range(4, 1, 1)
range(1, 4, -1)
range(2.5)
range(0, 2.5)
range(1, 2, 0.5)
range(-1, -4, -1)
range("3")
range("a")
range(null)
range(1, null)
range(5, 5)
range(0, 10, 100)
range(0, -10, -100)
range(0, 1000000000)
range(10000)[9999]
length(range(1024))
length(range(1025))
length(range(0, 1, 0.001))
range(1, 2, 0.1)
range(0.1, 0.5, 0.1)
range(-2.5, 2.5, 2.5)
reverse([1,2,3])
reverse([])
reverse(["a"])
reverse([1,"a"])
reverse(tolist([1,2]))
reverse(toset([1,2]))
reverse("abc")
reverse(null)
reverse({a=1})
reverse([[1],[2]])
slice([1,2,3], 0, 2)
slice([1,2,3], 1, 3)
slice([1,2,3], 0, 3)
slice([1,2,3], 0, 4)
slice([1,2,3], 3, 3)
slice([1,2,3], 2, 1)
slice([1,2,3], -1, 2)
slice([1,2,3], 0, -1)
slice([], 0, 0)
slice([1,2,3], 1.5, 2)
slice([1,2,3], "1", "2")
slice(["a","b"], 1, 2)
slice(tolist([1,2,3]), 1, 2)
slice(toset([1,2,3]), 1, 2)
slice([1,"a",true], 0, 2)
slice("abc", 0, 1)
slice(null, 0, 1)
slice([1], null, 1)
slice([1,2,3], 4, 4)
sort(["b","a","c"])
sort([])
sort(["B","a","C"])
sort(["a","B","A","b"])
sort(["é","e","z","f"])
sort(["10","9","1"])
sort([3,1,2])
sort([1,"a"])
sort(["a", null])
sort(toset(["b","a"]))
sort(tolist(["b","a"]))
sort([true,false])
sort([[1]])
sort(null)
sort("a")
sort(["a","a"])
sort(["é","é"])
sort(["😀","z","￿"])
sort(["", "a", " "])
sort(["a1","a10","a2"])
sort([1.5,1,"0.5"])
sort([10, 9, 1.5])
sort(["Z","a"])
sort(["ab","a","abc",""])
setunion([1,2],[2,3])
setunion([1],[2],[3])
setunion([])
setunion([], [])
setunion(["a","b"], ["b","c"])
setunion([1], ["a"])
setunion([1], [true])
setunion([1], [[1]])
setunion([[1]], [[2]])
setunion([[1]], [[1]])
setunion([{a=1}], [{a=2}])
setunion([{a=1}], [{b=2}])
setunion(toset([1]), [2])
setunion(tolist([1]), tolist([2]))
setunion([1], null)
setunion([1], "a")
setunion([1,1], [1])
setunion([3,1,2])
setunion(["b","a"])
setunion(["a","B","A","b"])
setunion([1.0], [1])
setunion(["1"], [1])
setunion([null], [1])
setunion([null], [null])
setunion({a=1}, [1])
setintersection([1,2,3],[2,3,4])
setintersection([1,2],[3])
setintersection([1,2])
setintersection([], [1])
setintersection([1,2],[2,3],[2,4])
setintersection(["a","b"],["b"])
setintersection([1],["1"])
setintersection([1,2], tolist([2]))
setintersection(toset([1,2]), toset([2]))
setintersection([[1],[2]], [[2]])
setintersection([{a=1}], [{a=1}])
setintersection([1], null)
setintersection()
setintersection([1], 1)
setintersection([1,2,3],[3,2,1])
setintersection(["b","a"],["a","b"])
setintersection([1], [true])
setintersection([null],[null])
setsubtract([1,2,3],[2])
setsubtract([1,2,3],[4])
setsubtract([1,2,3],[1,2,3])
setsubtract([],[1])
setsubtract([1],[])
setsubtract(["a","b"],["b"])
setsubtract([1],["1"])
setsubtract([[1],[2]],[[1]])
setsubtract([1], null)
setsubtract([1])
setsubtract([1],[2],[3])
setsubtract(toset([1,2]), toset([2]))
setsubtract(tolist([1,2]), tolist([2]))
setsubtract(1, [1])
setsubtract([3,1,2],[9])
setproduct([1,2],["a","b"])
setproduct([1],[2],[3])
setproduct([1,2])
setproduct([], [1])
setproduct([1], [])
setproduct()
setproduct([1,2], [3,4], [5,6])
setproduct(["a","b"], ["a"])
setproduct(toset([1,2]), ["a"])
setproduct(tolist([1,2]), ["a"])
setproduct([1,"a"], [true])
setproduct([[1]], [2])
setproduct([{a=1}], [2])
setproduct({a=[1,2]})
setproduct({a=[1,2], b=["x","y"]})
setproduct({a=[1]}, [2])
setproduct({})
setproduct({a=[]})
setproduct({a=[1],b=[2]}, {c=[3]})
setproduct(null)
setproduct([1], null)
setproduct("a", [1])
setproduct(tomap({a=["x"]}))
setproduct({a=toset([1,2])})
setproduct({b=[1,2], a=["x"]})
setproduct([1,1],[2])
length(setproduct(range(3), range(4)))
zipmap(["a","b"], [1,2])
zipmap([], [])
zipmap(["a"], [1,2])
zipmap(["a","b"], [1])
zipmap(["a","a"], [1,2])
zipmap(["a","b"], [1,"x"])
zipmap(["a","b"], [[1],[2]])
zipmap(["a","b"], [[1],["x"]])
zipmap(["a","b"], [{x=1},{y=2}])
zipmap([1,2], [3,4])
zipmap(["a"], toset([1]))
zipmap(toset(["a"]), [1])
zipmap(tolist(["a"]), tolist([1]))
zipmap(["a",null], [1,2])
zipmap([[1]], [1])
zipmap("a", [1])
zipmap(["a"], null)
zipmap(null, [1])
zipmap({a=1}, [1])
zipmap(["a"], {a=1})
zipmap(["b","a"], [1,2])
zipmap([true], [1])
zipmap(["a","b"], [null, 1])
coalesce("a", "b")
coalesce(null, "b")
coalesce("", "b")
coalesce("", null, "c")
coalesce(null, null)
coalesce()
coalesce(null)
coalesce("")
coalesce(1, 2)
coalesce(null, 1)
coalesce(0, 1)
coalesce(false, true)
coalesce(null, false)
coalesce(1, "a")
coalesce(null, "1")
coalesce(null, 1, "a")
coalesce([1], [2])
coalesce(null, [1])
coalesce([], [1])
coalesce({}, {a=1})
coalesce(null, {a=1})
coalesce("a", 1)
coalesce("a", [1])
coalesce("a", {})
coalesce(null, "", "b")
coalesce(" ", "b")
coalesce(true, "a")
coalesce(false, "a")
coalesce(null, true, "a")
coalesce(1.5, "a")
coalesce(null, tolist([1]))
coalesce(null, toset([1]))
coalesce(tolist([]), tolist([1]))
coalescelist([], [1])
coalescelist([1], [2])
coalescelist([], [])
coalescelist()
coalescelist(null, [1])
coalescelist([])
coalescelist(["a"], [1])
coalescelist([], ["a"], [1])
coalescelist(tolist([]), tolist([1]))
coalescelist(toset([]), toset([1]))
coalescelist([], toset([1]))
coalescelist("a")
coalescelist({a=1})
coalescelist([null])
coalescelist([[1]], [2])
coalescelist([], [1], [2])
compact(["a","","b"])
compact(["a",null,"b"])
compact([])
compact([""])
compact([null])
compact(["a"," ","b"])
compact([1,2])
compact(["a",1,""])
compact([true,""])
compact(toset(["a",""]))
compact(tolist(["a",""]))
compact([["a"]])
compact("a")
compact(null)
compact({a="b"})
compact(["", null, ""])
compact(["b","a"])
compact([{a=1}])
one([])
one([1])
one([1,2])
one(["a"])
one(tolist([]))
one(toset([1]))
one(toset([1,2]))
one(tolist([1]))
one([null])
one(null)
one({})
one({a=1})
one("a")
one([[1]])
one([{a=1}])
one([1,1])
one(toset([]))
one(tolist([null]))
sum([1,2,3])
sum([])
sum([1.5,2.5])
sum(["1","2"])
sum([1,"2"])
sum([0.1,0.2])
sum([1,null])
sum([null])
sum(["a"])
sum([true])
sum(toset([1,2]))
sum(tolist([1,2]))
sum([1e100,1])
sum([[1]])
sum(1)
sum(null)
sum({a=1})
sum([-1,1])
sum([1/3,1/3,1/3])
sum(["1.5"," 2"])
sum([10000000000000000000000000,1])
alltrue([true,true])
alltrue([true,false])
alltrue([])
alltrue(["true"])
alltrue(["true","false"])
alltrue([null])
alltrue([true,null])
alltrue([1])
alltrue(["a"])
alltrue(["TRUE"])
alltrue(toset([true]))
alltrue(tolist([true,true]))
alltrue(true)
alltrue(null)
alltrue([[true]])
alltrue({a=true})
alltrue(["1"])
alltrue([0])
anytrue([true,false])
anytrue([false,false])
anytrue([])
anytrue(["true"])
anytrue([null])
anytrue([null,true])
anytrue([false,null])
anytrue([1])
anytrue(["a"])
anytrue(toset([false]))
anytrue(true)
anytrue(null)
anytrue({a=true})
anytrue(["false","true"])
chunklist([1,2,3,4,5], 2)
chunklist([1,2,3,4], 2)
chunklist([], 2)
chunklist([1,2,3], 5)
chunklist([1,2,3], 1)
chunklist([1,2,3], 0)
chunklist([1,2,3], -1)
chunklist([], 0)
chunklist([1,2,3], 1.5)
chunklist([1,2,3], "2")
chunklist(["a","b","c"], 2)
chunklist([1,"a",true], 2)
chunklist(tolist([1,2,3]), 2)
chunklist(toset([1,2,3]), 2)
chunklist([[1],[2]], 1)
chunklist("abc", 1)
chunklist(null, 1)
chunklist([1], null)
chunklist([{a=1},{a=2}], 1)
chunklist([1,2,3], 3)
chunklist([1,2,3], 2.0)
transpose({a=["1","2"], b=["2","3"]})
transpose({})
transpose({a=[]})
transpose({a=["1"]})
transpose({a=["1","1"]})
transpose({a=["x","y"], b=["y"]})
transpose(tomap({a=["1","2"]}))
transpose({a=[1,2]})
transpose({a=["1"], b=[2]})
transpose({a="1"})
transpose({a=[["1"]]})
transpose([["1"]])
transpose(null)
transpose({a=null})
transpose({a=[null]})
transpose({b=["1"], a=["1","2"]})
transpose({a=toset(["1"])})
transpose({a=tolist(["2","1"])})
transpose({a=["1"], b=[]})
transpose({a=[true]})
matchkeys(["a","b","c"], ["x","y","z"], ["y","z"])
matchkeys(["a","b"], ["x","y"], [])
matchkeys(["a","b"], ["x","y"], ["q"])
matchkeys([1,2,3], ["x","y","z"], ["z","x"])
matchkeys(["a"], ["x","y"], ["x"])
matchkeys(["a","b"], ["x"], ["x"])
matchkeys([], [], [])
matchkeys(["a","b"], [1,2], [2])
matchkeys(["a","b"], ["1","2"], [2])
matchkeys(tolist(["a","b"]), tolist(["x","y"]), tolist(["y"]))
matchkeys(["a","b"], ["x","y"], toset(["y"]))
matchkeys(["a",1], ["x","y"], ["y"])
matchkeys(null, ["x"], ["x"])
matchkeys("a", ["x"], ["x"])
matchkeys([{a=1},{a=2}], ["x","y"], ["y"])
tolist([1,2])
tolist(["b","a"])
tolist(toset(["b","a"]))
tolist(toset([3,1,2]))
tolist([])
tolist([1,"a"])
tolist([1,true])
tolist([[1],["a"]])
tolist([[1],[2]])
tolist([{a=1},{a=2}])
tolist([{a=1},{b=2}])
tolist([{a=1},{a="x"}])
tolist({a=1})
tolist("a")
tolist(null)
tolist(1)
tolist([null])
tolist([null,1])
tolist([null, "a"])
tolist(tolist([1]))
tolist(tomap({a=1}))
tolist([1,[2]])
tolist([1,{a=2}])
tolist([[1],{a=1}])
tolist([true,"a"])
tolist(["1", 2])
tolist([1.5, "a"])
tolist([{a=1,b="x"},{a=2,b="y"}])
tolist([{a=1},{a=null}])
toset([3,1,2])
toset(["b","a","b"])
toset([])
toset([1,"a"])
toset([1,"1"])
toset([1,true])
toset([[1],[2]])
toset([[1],[1]])
toset([{a=1},{a=1}])
toset([{a=1},{a=2}])
toset(["a","B","A","b"])
toset([true,false])
toset([1.5,1,0.5])
toset(toset([1]))
toset(tolist([2,1]))
toset(null)
toset("a")
toset({a=1})
toset([null])
toset([1,null])
toset([[1,2],[1]])
toset([[2],[1]])
toset([[1],[10],[2]])
toset([["a"],["b"],["c"]])
toset([{a=1},{a=3},{a=2}])
toset([{b=1},{a=1}])
toset([{a="x"},{a="y"},{a="z"}])
toset([{a=1,b=2},{a=2,b=1}])
toset([[1,"a"],[2,"b"]])
toset(["é","e","z"])
toset([10,9,100,-1])
toset(["10","9","100"])
tomap({a=1})
tomap({a=1,b="x"})
tomap({a=1,b=true})
tomap({a=[1],b=["x"]})
tomap({a=[1],b=[2]})
tomap({a={x=1},b={x=2}})
tomap({a={x=1},b={y=2}})
tomap({a={x=1},b={x="s"}})
tomap({})
tomap(null)
tomap("a")
tomap([1])
tomap({a=null})
tomap({a=null,b=1})
tomap({a=1,b=null})
tomap(tomap({a=1}))
tomap({a=[1],b={x=1}})
tomap({a=1,b=[1]})
tomap({a=tolist([1])})
tomap({a="x",b=tolist([1])})
tomap([{a=1}])
tomap({b=2,a=1})
tomap({a={x=1}})
tomap({a={x=[1]},b={x=["y"]}})
tomap({a=[{x=1}],b=[{x=2}]})
tomap({a=[{x=1}],b=[{y=2}]})
''')


def numeric_exprs() -> list[str]:
    return _lines(r'''
abs(-1)
abs(1)
abs(0)
abs(-0.5)
abs("-3")
abs(-1e100)
abs(true)
abs("x")
abs(null)
abs([1])
abs(-12345678901234567890)
ceil(1.1)
ceil(1)
ceil(-1.1)
ceil(-0.5)
ceil(0.0000001)
ceil("1.5")
ceil(1e100)
ceil(12345678901234567890.5)
ceil(null)
ceil("a")
ceil(true)
floor(1.9)
floor(-1.1)
floor(-0.5)
floor(1)
floor(0.9999999999999999999999)
floor("1.5")
floor(1e100)
floor(null)
floor(-1e-10)
log(100, 10)
log(8, 2)
log(1, 10)
log(0, 10)
log(-1, 10)
log(10, 1)
log(10, 0)
log(10, -1)
log(2.718281828459045, 2.718281828459045)
log(1000, 10)
log(64, 4)
log(100, 3)
log("100", "10")
log(null, 10)
log(1e100, 10)
log(2, 2)
log(0.5, 2)
log(10, 10)
log(1e-5, 10)
log(125, 5)
log(0.001, 10)
log(243, 3)
log(4096, 2)
log(3, 3)
log(true, 2)
max(1, 2, 3)
max(3)
max()
max(1.5, 1)
max("1", 2)
max([1,2])
max([1,2]...)
max(1, "a")
max(1, null)
max(-1, -2)
max(1e100, 1)
max(0.1, 0.2)
max(1, true)
max([]...)
max(1/3, 0.33)
min(1, 2, 3)
min(3)
min()
min(1.5, 1)
min("1", 2)
min([3,2]...)
min(1, "a")
min(-1, -2)
min(1e-100, 1)
min([]...)
min(null)
min(1, 1.0)
pow(2, 3)
pow(2, 0)
pow(2, -1)
pow(2, 0.5)
pow(0, 0)
pow(0, -1)
pow(-8, 1/3)
pow(-2, 3)
pow(-2, 2)
pow(10, 20)
pow(10, 100)
pow(2, 100)
pow(2, 1000)
pow(1.5, 2)
pow(1.1, 10)
pow(0.5, 3)
pow("2", "3")
pow(2, null)
pow(1, 100000)
pow(7, 77)
pow(2, 3.5)
pow(10, -3)
pow(10, -20)
pow(3, -2)
pow(-1, 0.5)
pow(2, 1e100)
pow(1e100, 2)
pow(0.1, 3)
pow(1/3, 3)
pow(9, 0.5)
pow(4, 0.5)
pow(2, 10)
pow(5, 0)
pow(0, 5)
pow(-0, 2)
pow(2, 64)
pow(2, 63)
pow(2, 62)
pow(12, 12)
signum(-5)
signum(0)
signum(3)
signum(-0.1)
signum(0.0001)
signum("5")
signum(null)
signum(true)
signum(-1e100)
parseint("100", 10)
parseint("FF", 16)
parseint("ff", 16)
parseint("-10", 2)
parseint("+10", 2)
parseint("0x10", 16)
parseint("0x10", 0)
parseint("010", 0)
parseint("0b11", 0)
parseint("0o17", 0)
parseint("1_000", 0)
parseint("1_000", 10)
parseint("", 10)
parseint("abc", 10)
parseint("12", 2)
parseint("12", 1)
parseint("12", 37)
parseint("z", 36)
parseint("Z", 36)
parseint("12.5", 10)
parseint(" 12", 10)
parseint("12 ", 10)
parseint("99999999999999999999", 10)
parseint("-99999999999999999999", 10)
parseint("ffffffffffffffffffff", 16)
parseint(12, 10)
parseint("12", "10")
parseint(null, 10)
parseint("12", null)
parseint("12", 10.5)
parseint("-", 10)
parseint("0", 10)
parseint("-0", 10)
parseint("1e3", 10)
parseint("١٢", 10)
parseint("7", 8)
parseint("8", 8)
parseint("101", 2.0)
parseint(true, 10)
parseint("12", 0)
parseint("0x", 0)
parseint("0", 0)
parseint("-0x1f", 0)
parseint("1f", 0)
parseint("12", -1)
tonumber("1")
tonumber("1.5")
tonumber("-1")
tonumber("+1")
tonumber(" 1")
tonumber("1 ")
tonumber("")
tonumber("a")
tonumber("1e3")
tonumber("1E3")
tonumber("0x10")
tonumber("1_000")
tonumber(".5")
tonumber("5.")
tonumber("0.5")
tonumber("00012")
tonumber("-0")
tonumber("Infinity")
tonumber("NaN")
tonumber("١")
tonumber(1)
tonumber(true)
tonumber("true")
tonumber(null)
tonumber([1])
tonumber({a=1})
tonumber("1e400")
tonumber("1e-400")
tonumber("123456789012345678901234567890")
tonumber("0.1")
tonumber("1.0")
tonumber("100e-2")
tonumber("1e+2")
tonumber("--1")
tonumber("1,5")
tonumber("0b1")
tonumber("1f")
tonumber(tostring(1.50))
tostring(1)
tostring(1.0)
tostring(1.50)
tostring(-0)
tostring(0.1)
tostring(1e20)
tostring(1e-20)
tostring(100000000000000000000)
tostring(1/3)
tostring(true)
tostring(false)
tostring("a")
tostring(null)
tostring([1])
tostring({a=1})
tostring([])
tostring(toset([1]))
tostring(12345678901234567890)
tostring(0.000001)
tostring(123.456)
tostring(1e100)
tostring(1e-100)
tostring(2/3)
tostring(10/4)
tostring(1e15)
tostring(1e16)
tostring(1e21)
tostring(123456789.123456789)
tobool(true)
tobool(false)
tobool("true")
tobool("false")
tobool("TRUE")
tobool("True")
tobool("1")
tobool("yes")
tobool("")
tobool(" true")
tobool(1)
tobool(0)
tobool(null)
tobool([true])
tobool({a=true})
tobool("t")
tobool("false ")
tobool(1.5)
''')


def type_exprs() -> list[str]:
    return _lines(r'''
[1,2][0]
[1,2][2]
[1,2][-1]
[1,2]["0"]
[1,2][1.5]
[1,2]["a"]
[1,2][true]
[1,2][null]
{a=1}.a
{a=1}.b
{a=1}["a"]
{a=1}["b"]
{a=1}[0]
{a=1}[null]
{"a b"=1}["a b"]
{a={b=[1,{c=2}]}}.a.b[1].c
{a={b=1}}.a.c
{a=1}.a.b
"abc"[0]
"abc".a
null.a
null[0]
[1,2].0
[[1,2],[3]][1][0]
[[1,2],[3]].0.1
[{a=1},{a=2}][*].a
[{a=1},{a=2}].*.a
[{a=1},{b=2}][*].a
{a=1}[*].a
[1,2][*]
null[*]
1[*]
"a"[*]
[[1],[2]][*][0]
[{a=[1,2]},{a=[3]}][*].a
[{a=[1,2]},{a=[3]}][*].a[0]
tolist([{a=1},{a=2}])[*].a
toset([{a=1}])[*].a
[for x in [1,2,3] : x * 2]
[for x in [1,2,3] : x * 2 if x > 1]
[for i, x in ["a","b"] : "${i}-${x}"]
[for x in {a=1,b=2} : x]
[for k, v in {a=1,b=2} : "${k}=${v}"]
[for x in toset([3,1,2]) : x]
[for x in [] : x]
[for x in null : x]
[for x in 1 : x]
[for x in "a" : x]
[for x in [1,2] : x if x > 5]
[for x in [1,"a"] : x]
[for x in [1,2] : [x]]
[for x in [1,2] : {v=x}]
{for x in [1,2] : x => x * 2}
{for x in ["a","b"] : x => upper(x)}
{for k, v in {a=1,b=2} : v => k}
{for x in [1,2] : "k${x}" => x}
{for x in ["a","a"] : x => 1}
{for x in ["a","a"] : x => 1...}
{for x in ["a","b","a"] : x => x...}
{for x in [1,2] : x => x if x > 1}
{for k, v in {a=1} : k => v}
{for x in [1] : true => x}
{for x in [1] : null => x}
{for x in [1] : [1] => x}
{for x in [1,2] : x => null}
{for i, x in ["a","b"] : x => i}
{for x in [] : x => x}
{for x in toset(["a"]) : x => 1}
[for x in [1,2,3] : x][1]
[for x in {b=1,a=2} : x]
[for k in keys({b=1,a=2}) : k]
[for x in tolist([1,2]) : x]
[for x in [[1,2],[3]] : length(x)]
[for x in [1,2] : x == 1 ? "one" : "other"]
[for x in [1,2] : x > 1 ? "a" : 1]
[for x in [[1],[2]] : x...]
1 + 2
1 - 2
2 * 3
7 / 2
1 / 3
-7 % 3
7 % -3
7 % 3
5.5 % 2
0.1 + 0.2
0.3 - 0.1
0.1 * 3
1 / 0
-1 / 0
0 / 0
1 % 0
0 * (1 / 0)
1e100 * 1e100
1e400
1e-400
100000000000000000000 + 1
99999999999999999999999999999999999999 * 99999999999999999999999999999999999999
2 - 3 * 4
(2 - 3) * 4
-(1)
- -1
!true
!false
!!true
!null
!1
!"true"
!"false"
!"a"
-"1"
-"a"
-true
-null
-[1]
1 + "2"
"1" + "2"
"a" + 1
1 + true
1 + null
null + 1
[1] + [2]
1 * "3"
"6" / "3"
1 == 1
1 == "1"
1 == 1.0
"1" == 1
1 == true
"a" == "a"
"a" != "a"
null == null
null == 1
null == "a"
null == []
[] == []
[1] == [1]
[1] == [2]
[1] == ["1"]
[1,2] == [1,2]
{a=1} == {a=1}
{a=1} == {a=2}
{a=1} == {b=1}
{a=1} == tomap({a=1})
[1] == tolist([1])
toset([1]) == toset([1])
toset([1]) == [1]
tolist([1]) == toset([1])
tolist([1,2]) == [2,1]
true == "true"
true == 1
1 < 2
2 < 1
1 <= 1
2 > 1
1 >= 2
1 < "2"
"a" < "b"
"1" < 2
true < false
null < 1
1 < null
[1] < [2]
1 < 1.5
0.1 + 0.2 == 0.3
1/3 * 3 == 1
1/3 * 3
true && false
true || false
true && "true"
"true" && true
"a" && true
1 && true
null && true
true && null
false && (1/0 > 0)
true || (1/0 > 0)
false && null
true || null
null || true
false || "false"
true && true && false
true || false && false
!true || true
1 == 1 && 2 == 2
true ? 1 : 2
false ? 1 : 2
true ? "a" : 1
false ? "a" : 1
true ? [1] : [2]
true ? [1] : ["a"]
true ? [1] : {a=1}
true ? {a=1} : {b=2}
true ? {a=1} : {a="x"}
false ? {a=1} : {b=2}
true ? null : 1
false ? 1 : null
null ? 1 : 2
"true" ? 1 : 2
"false" ? 1 : 2
"a" ? 1 : 2
1 ? 1 : 2
true ? [] : [1]
true ? tolist([]) : tolist([1])
true ? tolist(["a"]) : toset(["b"])
true ? tolist([1]) : ["a"]
false ? tolist([1]) : [1]
true ? toset([1]) : toset([2])
true ? 1 : 1/0
false ? 1/0 : 2
true ? tomap({a=1}) : {b=2}
true ? tomap({a=1}) : {a="x"}
true ? "a" : null
true ? 1 : "1"
true ? [1,2] : [3]
true ? {a=1} : null
1 > 0 ? "pos" : "neg"
[1,2,3][1] + 1
[for x in [1,2] : x][0]
{a=1}.a + 1
length([for x in range(5) : x if x % 2 == 0])
"a${1}b"
"a${1 + 1}b"
"${1}"
"${1}${2}"
"${true}"
"${null}"
"a${null}b"
"${[1]}"
"${{a=1}}"
"${"nested"}"
"${"a${"b"}"}"
"$${1}"
"$${"
"$"
"a$"
"$a"
"${1}$"
"%{ if true }yes%{ endif }"
"%{ if false }yes%{ endif }"
"%{ if true }yes%{ else }no%{ endif }"
"%{ if false }yes%{ else }no%{ endif }"
"%{ if 1 }yes%{ endif }"
"%{ if "true" }yes%{ endif }"
"%{ if null }yes%{ endif }"
"%{ if "a" }yes%{ endif }"
"%{ for x in [1,2,3] }${x},%{ endfor }"
"%{ for x in [1,2,3] }${x}%{ if x < 3 },%{ endif }%{ endfor }"
"%{ for i, x in ["a","b"] }${i}=${x};%{ endfor }"
"%{ for k, v in {a=1,b=2} }${k}=${v};%{ endfor }"
"%{ for x in [] }${x}%{ endfor }"
"%{ for x in null }${x}%{ endfor }"
"%{ for x in toset(["b","a"]) }${x}%{ endfor }"
"%{ for x in [1,2] }%{ for y in [3,4] }${x}${y} %{ endfor }%{ endfor }"
"%{ for x in [1,2] }${x}%{ else }none%{ endfor }"
"%{ for x in [1,2]}${x}%{endfor}"
"%{~ for x in [1,2] ~}\n${x}\n%{~ endfor ~}"
"a  %{~ if true ~}  b  %{~ endif ~}  c"
"a  %{~ if true }  b  %{ endif ~}  c"
"a\n%{~ if true ~}\nb\n%{~ endif ~}\nc"
"a ${~ 1 ~} b"
"a ${~ 1 } b"
"a ${ 1 ~} b"
"a\n  ${~ "x" ~}\n  b"
"%%{ if true }"
"%%{"
"%{"
"%{ if true }"
"%{ endif }"
"%{ else }"
"%{ if true }a%{ else }b%{ else }c%{ endif }"
"%{ for x in [1] }"
"%{ if true }a%{ endfor }"
"%{ foo }"
"%{ if }a%{ endif }"
"${"
"${1"
"${}"
"${ }"
"a ${1} b ${2} c"
"${upper("a")}"
"${upper(1)}"
"${[1,2][0]}"
"${length([1,2])}"
"${1 == 1}"
"${1 > 2 ? "a" : "b"}"
"${toset([1])}"
"${tolist([1])}"
"${1.50}"
"${1/3}"
"${true ? "a" : "b"}"
"line1\nline2"
"tab\tq\"q"
"\\"
"é"
"\U0001F600"
"\x41"
"\q"
"\u12"
"\u{41}"
"a\
b"
[for x in [1] : "${x}"]
"${[for x in [1,2] : x * 2]}"
"${join(",", [for x in [1,2] : x])}"
{a=1, b=2}
{a=1, b=2,}
{"a"=1}
{"a": 1}
{a: 1}
{(1)=1}
{(1+1)="x"}
{(null)=1}
{("a")=1}
{a=1, a=2}
{a=1}
{1=1}
{1.5=1}
{true=1}
{"1"=1, 1=2}
{a=[1,2], b={c=3}}
[1,2,]
[,]
[1,,2]
[]
{}
[[]]
[{}]
{a={}}
{a=[]}
{ a = 1 }
1e3
1E3
1e+3
1.5e3
.5
5.
0x10
0b1
0o7
1_000
010
00
0
-0
-0.0
1.0
1.50
100000000000000000000
0.1
0.30000000000000004
123456789012345678901234567890.123456789
1e-3
1e3 + 1
true
false
null
TRUE
True
"a" "b"
'a'
local.x
var.x
path.module
path.root
terraform.workspace
count.index
each.key
self.x
data.a.b
foo
foo(1)
upper
upper()
upper("a", "b")
upper("a",)
upper("a"...)
upper(["a"]...)
upper(["a","b"]...)
max([1,2,3]...)
max([1,2],[3]...)
max(1,[2,3]...)
max([]...)
min(tolist([2,1])...)
min(toset([2,1])...)
min({a=1}...)
min(1...)
min(null...)
length(...)
format("%s-%s", ["a","b"]...)
format("%s-%s", tolist(["a","b"])...)
concat([[1],[2]]...)
merge([{a=1},{b=2}]...)
merge(tolist([{a=1},{b=2}])...)
coalesce(["a","b"]...)
coalesce([null,"b"]...)
''')


def all_exprs() -> list[str]:
    return collection_exprs() + numeric_exprs() + type_exprs()
