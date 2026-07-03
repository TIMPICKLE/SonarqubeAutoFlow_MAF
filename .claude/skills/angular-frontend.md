# Angular Frontend Fix Skill

修复 Angular 19 + NG-ZORRO 前端代码问题，遵循 Angular 最佳实践和项目规范。

## 触发条件

当用户需要修复以下类型的前端代码问题时使用此 skill：
- Angular 组件、服务、模块相关问题
- TypeScript 代码异味（SonarQube 规则）
- NG-ZORRO 组件使用问题
- RxJS 响应式编程问题
- 表单处理、状态管理问题

## Angular 核心原则

### 组件开发规范
- 选择器使用 kebab-case
- 类名使用 PascalCase，以 `Component` 结尾
- 服务类以 `Service` 结尾
- 使用 TypeScript 访问修饰符
- 逻辑保持在 TypeScript 中，模板保持简洁

### 生命周期管理
- 明确实现使用的生命周期接口：`OnInit, AfterViewInit, OnDestroy`
- 使用 `OnPush` 变更检测策略
- 在 `ngOnDestroy` 中正确清理资源

### 响应式编程
- 优先使用 RxJS Observables
- 避免嵌套订阅，使用组合操作符：`switchMap, mergeMap, concatMap`
- 使用 `takeUntil` 模式避免内存泄漏：
```typescript
private destroy$ = new Subject<void>();

ngOnInit() {
  this.service.getData()
    .pipe(takeUntil(this.destroy$))
    .subscribe(/* ... */);
}

ngOnDestroy() {
  this.destroy$.next();
  this.destroy$.complete();
}
```
- 适当使用 `async` 管道自动管理订阅

### 状态管理
- ABP 模式通过 NgRx 管理状态
- 本地状态使用 `BehaviorSubject` 或 `ReplaySubject`
- 通过 Observable 暴露状态
- 使用不可变更新模式

## NG-ZORRO 组件规范

### 布局组件
- 使用 `nz-layout, nz-header, nz-content, nz-footer, nz-sider`
- 使用 `nz-row, nz-col` 栅格系统
- 响应式断点：xs(<576px), sm(≥576px), md(≥768px), lg(≥992px), xl(≥1200px), xxl(≥1600px)

### 表单处理
- 响应式表单 + NG-ZORRO 控件
- 使用 `FormBuilder` 创建表单
- 使用 `nzErrorTip` 显示验证消息
- 表单布局：水平、垂直、内联

### 数据展示
- 使用 `nz-table` 进行表格展示
- 使用 `nz-card, nz-list, nz-tree` 展示数据
- 使用 `nz-typography` 保持文本一致性

### 交互组件
- 使用 `NzModalService` 创建模态框
- 使用 `NzMessageService` 和 `NzNotificationService` 显示消息
- 使用 `nz-popconfirm` 进行操作确认
- 使用 `nz-drawer` 实现侧边抽屉

## TypeScript 编码规范

### 文件命名
- 连字符命名：`feature-name.component.ts`
- 明确后缀：`.component.ts, .service.ts, .module.ts, .pipe.ts, .directive.ts`

### 编码风格
- 严格模式：`"strict": true`
- 避免使用 `any` 类型
- 使用接口定义数据模型
- 使用枚举表示固定值集合
- 每个文件一个组件/服务
- 为成员使用访问修饰符

### 样式规范
- LESS 中使用变量和混合宏
- 使用 NG-ZORRO 断点实现响应式
- 组件封装样式，避免全局样式
- 避免内联样式

### 性能优化
- 实现 `OnPush` 变更检测
- 使用 `trackBy` 优化 `ngFor`
- 避免模板中复杂计算
- 延迟加载非关键模块

## 修复流程

1. **分析问题**：理解 SonarQube 规则或问题描述
2. **定位代码**：找到相关 TypeScript/HTML/LESS 文件
3. **评估影响**：检查是否涉及组件、服务、模板多文件
4. **应用修复**：按照 Angular 规范修改代码
5. **验证修复**：确保不破坏现有功能

## 常见修复模式

### S1481 - 未使用的变量
```typescript
// Before
const result = this.service.getData();

// After (如果订阅是目的)
this.service.getData().subscribe();
```

### S3353 - 未使用的私有字段
```typescript
// Before
private unusedField: string;

// After - 删除未使用字段
```

### S4137 - 可简化的条件表达式
```typescript
// Before
if (this.isValid === true) { }

// After
if (this.isValid) { }
```

### S4157 - 空订阅应使用 tap
```typescript
// Before
this.service.getData().subscribe();

// After - 如果只是触发副作用
this.service.getData().pipe(
  tap(() => this.logger.log('Data fetched'))
).subscribe();
```

### S2933 - 可改为 const 的变量
```typescript
// Before
let config = this.getConfig();

// After
const config = this.getConfig();
```

### 订阅内存泄漏修复
```typescript
// Before
ngOnInit() {
  this.service.data$.subscribe(d => this.data = d);
}

// After
private destroy$ = new Subject<void>();

ngOnInit() {
  this.service.data$.pipe(
    takeUntil(this.destroy$)
  ).subscribe(d => this.data = d);
}

ngOnDestroy() {
  this.destroy$.next();
  this.destroy$.complete();
}
```

## ABP Angular 集成

### 国际化
- 管道：`{{ '::ResourceKey' | abpLocalization }}`
- 服务：`this.l('ResourceKey')`
- 避免硬编码文本

### 权限管理
- 指令：`abpPermission` 指令
- 服务：权限管理服务控制 UI 显示
- 基于角色和权限的访问控制

## 参考资源

- Angular 风格指南: https://angular.io/guide/styleguide
- NG-ZORRO 文档: https://ng.ant.design
- ABP Angular UI: https://docs.abp.io/en/abp/latest/UI/Angular
- RxJS 文档: https://rxjs.dev
