# TypeScript Common Fix Skill

修复通用 TypeScript 代码问题，遵循 TypeScript 最佳实践和编码规范。

## 触发条件

当用户需要修复以下类型的 TypeScript 代码问题时使用此 skill：
- TypeScript 类型安全问题
- ES6+ 语法优化
- 代码简洁性和可读性问题
- 通用 SonarQube 规则修复

## TypeScript 核心原则

### 类型安全
- 启用严格模式：`"strict": true`
- 避免 `any` 类型，使用具体类型或泛型
- 使用类型推断，但显式标注公共 API
- 使用联合类型和交叉类型表达复杂类型
- 使用类型守卫缩小类型范围

### 接口与类型
- 使用 `interface` 定义对象形状
- 使用 `type` 定义联合类型、交叉类型、映射类型
- 使用 `readonly` 标记不可变属性
- 使用可选属性 `?` 表达可选字段

### 空值处理
- 使用 `undefined` 表示缺失值（避免 `null`）
- 使用可选链 `?.` 访问可能为空的属性
- 使用空值合并 `??` 提供默认值
- 使用非空断言 `!` 仅在确定非空时

### 函数设计
- 使用箭头函数保持 `this` 上下文
- 使用默认参数代替条件检查
- 使用剩余参数和展开运算符
- 使用函数重载表达多种调用签名

## 编码规范

### 命名约定
- PascalCase：类、接口、类型、枚举、命名空间
- camelCase：变量、参数、函数、方法、属性
- UPPER_SNAKE_CASE：全局常量
- 前缀 `I` 用于接口（可选，但保持一致）

### 代码组织
- 每个文件一个主要导出
- 导入顺序：标准库 → 第三方库 → 本地模块
- 导出顺序：类型 → 常量 → 函数 → 类
- 使用 `export default` 仅在单一导出时

### 代码风格
- 使用 `const` 优先，`let` 仅在需要重新赋值时
- 使用模板字符串代替字符串拼接
- 使用解构赋值简化代码
- 使用展开运算符复制数组和对象
- 使用 `for...of` 遍历数组
- 使用 `Object.entries/values/keys` 遍历对象

### 异步编程
- 使用 `async/await` 处理 Promise
- 使用 `Promise.all` 并行执行
- 使用 `Promise.allSettled` 处理部分失败
- 正确处理 Promise 异常

## 修复流程

1. **分析问题**：理解 SonarQube 规则或问题描述
2. **确定类型影响**：检查类型定义和依赖
3. **应用修复**：按照 TypeScript 规范修改代码
4. **类型检查**：确保修复后类型正确

## 常见修复模式

### S1481 - 未使用的变量
```typescript
// Before
const temp = calculate();

// After
calculate(); // 如果确实不需要结果
// 或使用 const _ = calculate(); 表示有意忽略
```

### S2933 - 应使用 const
```typescript
// Before
let config = { timeout: 1000 };

// After
const config = { timeout: 1000 };
```

### S4137 - 条件表达式可简化
```typescript
// Before
if (value === true) { }
if (array.length > 0) { }

// After
if (value) { }
if (array.length) { }
```

### S3353 - 未使用的私有字段
```typescript
// Before
class Example {
  private unusedField: string;
}

// After - 删除未使用字段
class Example {
}
```

### S4157 - 空函数应添加注释
```typescript
// Before
ngAfterContentInit() {}

// After
ngAfterContentInit() {
  // 故意为空：此组件不需要处理内容初始化
}
```

### S4123 - 空接口应使用类型别名
```typescript
// Before
interface EmptyConfig {}

// After
type EmptyConfig = Record<string, never>;
// 或删除如果确实不需要
```

### S1854 - 未使用的赋值
```typescript
// Before
let result: string;
if (condition) {
  result = 'a';
}
// result 从未被使用

// After
if (condition) {
  doSomethingWith('a');
}
```

### S3776 - 认知复杂度降低
```typescript
// Before - 嵌套条件
function process(data: Data) {
  if (data) {
    if (data.items) {
      if (data.items.length > 0) {
        return data.items[0];
      }
    }
  }
  return null;
}

// After - 提前返回
function process(data: Data) {
  if (!data?.items?.length) {
    return null;
  }
  return data.items[0];
}
```

### S4326 - 使用可选链
```typescript
// Before
const name = user && user.profile && user.profile.name;

// After
const name = user?.profile?.name;
```

### S4327 - 使用空值合并
```typescript
// Before
const value = input !== null && input !== undefined ? input : defaultValue;

// After
const value = input ?? defaultValue;
```

### S4622 - 使用展开运算符
```typescript
// Before
const newArray = array.slice();
const newObject = Object.assign({}, obj);

// After
const newArray = [...array];
const newObject = { ...obj };
```

### S4323 - 使用解构
```typescript
// Before
const first = array[0];
const second = array[1];
const name = user.name;
const age = user.age;

// After
const [first, second] = array;
const { name, age } = user;
```

## 性能优化模式

### 避免重复计算
```typescript
// Before
array.filter(x => x.id === getId()).map(x => x.value);

// After
const targetId = getId();
array.filter(x => x.id === targetId).map(x => x.value);
```

### 使用 Set 优化查找
```typescript
// Before - O(n)
const exists = array.includes(item);

// After - O(1)
const set = new Set(array);
const exists = set.has(item);
```

### 使用 Map 优化映射
```typescript
// Before
const item = array.find(x => x.id === id);

// After
const map = new Map(array.map(x => [x.id, x]));
const item = map.get(id);
```

## 参考资源

- TypeScript 官方手册: https://www.typescriptlang.org/docs/handbook/
- TypeScript 编码规范: https://typescripttolua.github.io/docs/coding-guidelines
- ESLint TypeScript 规则: https://typescript-eslint.io/rules/
- SonarQube TypeScript 规则: https://rules.sonarsource.com/typescript/
