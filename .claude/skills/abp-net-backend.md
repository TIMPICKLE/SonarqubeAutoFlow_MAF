# ABP .NET Backend Fix Skill

修复 ABP .NET 后端代码问题，遵循 ABP 框架 5.1+ 最佳实践和 C# 编码规范。

## 触发条件

当用户需要修复以下类型的后端代码问题时使用此 skill：
- ABP 应用服务、仓储、领域服务相关问题
- C# 代码异味（SonarQube 规则）
- DDD 实体、聚合根设计问题
- 权限、验证、异常处理问题
- 异步编程模式问题

## ABP 框架核心原则

### 应用服务规范
- 继承 `ApplicationService` 基类
- 定义并实现 `IXxxAppService` 接口
- 使用 DTO 作为输入输出
- 使用 `IObjectMapper` 进行对象映射
- 正确应用 `[Authorize]` 特性

### 仓储模式
- 使用 `IRepository<TEntity, TKey>` 进行 CRUD
- 异步方法优先：`GetAsync`, `InsertAsync`, `UpdateAsync`, `DeleteAsync`
- 使用 `IQueryable` 扩展进行过滤、排序、分页

### 工作单元
- 服务自动参与环境工作单元
- 需要时显式应用 `[UnitOfWork]` 特性
- 使用 `IUnitOfWorkManager` 进行手动控制

### 安全与授权
- 在 `PermissionDefinitionProvider` 中定义权限
- 使用 `ICurrentUser` 获取用户信息
- 使用权限检查保护应用服务

### 验证系统
- 使用数据注解或 FluentValidation
- 抛出 `UserFriendlyException` 处理业务异常
- 利用 ABP 自动验证

## C# 编码规范

### 命名约定
- PascalCase：命名空间、类、接口、方法、属性、枚举
- camelCase：私有字段（带 `_` 前缀）、参数、局部变量
- 接口以 `I` 开头

### 代码组织
- 文件范围命名空间：`namespace Example;`
- 类成员顺序：常量 → 字段 → 构造函数 → 属性 → 方法 → 事件
- 每行不超过 120 字符
- 4 空格缩进，Allman 风格大括号

### 代码风格
- 类型明显时使用 `var`
- 优先字符串插值 `$"{value}"`
- 使用 `nameof` 表达式
- 使用 `?.` 和 `??` 空操作符
- `async`/`await` 异步编程
- 文件顶部 `#nullable enable`

### 异常处理
- 捕获特定异常，避免空 catch
- 重新抛出用 `throw;` 而非 `throw ex;`
- 自定义异常以 "Exception" 结尾

## 修复流程

1. **分析问题**：理解 SonarQube 规则或问题描述
2. **定位代码**：找到相关文件和代码位置
3. **评估影响**：检查是否涉及多文件修改（接口/实现）
4. **应用修复**：按照 ABP 模式和 C# 规范修改代码
5. **验证修复**：确保不破坏现有功能

## 常见修复模式

### S1481 - 未使用的局部变量
```csharp
// Before
var result = Calculate();

// After (如果确实不需要)
Calculate();
```

### S2325 - 方法可改为静态
```csharp
// Before
public string FormatName(string name) => name.Trim();

// After
public static string FormatName(string name) => name.Trim();
```

### S1123 - 废弃标记应说明原因
```csharp
// Before
[Obsolete]

// After
[Obsolete("Use NewMethod instead. This will be removed in v2.0.")]
```

### S4457 - 参数验证应在方法开头
```csharp
// Before
public void Process(string data)
{
    _logger.Log("Starting");
    if (string.IsNullOrEmpty(data))
        throw new ArgumentException("Data required");
    // ...
}

// After
public void Process(string data)
{
    if (string.IsNullOrEmpty(data))
        throw new ArgumentException("Data required");
    _logger.Log("Starting");
    // ...
}
```

## 参考资源

- ABP 5.1 文档: https://abp.io/docs/5.1
- C# 编码约定: https://learn.microsoft.com/dotnet/csharp/fundamentals/coding-style/coding-conventions
