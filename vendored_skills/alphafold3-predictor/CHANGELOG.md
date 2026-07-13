# AlphaFold3 Skill 更新日志

## 2025-04-19 - 多GPU并行支持与bug修复

### 新增功能
- ✅ **多GPU并行处理** - 支持在多个GPU上同时运行多个任务
  - 自动round-robin任务分配
  - 并行效率 ~83% (3 GPUs, 2.5x speedup)
  - 支持灵活的GPU指定: `--gpus 1,2,3` 或 `--gpus 0,1,2,3,4,5,6,7`

### Bug修复

#### 1. 单链蛋白格式化错误
**问题**: 单链蛋白没有pTM/ipTM指标时，格式化字符串导致错误
```
TypeError: unsupported format string passed to NoneType.__format__
```

**修复**: 修改结果汇总逻辑，正确处理None值
```python
# Before
print(f"    {job}: pTM={metrics['ptm']:.3f} ipTM={metrics['iptm']:.3f}")

# After
ptm = metrics['ptm']
iptm = metrics['iptm']
if isinstance(ptm, (int, float)) and isinstance(iptm, (int, float)):
    print(f"    {job}: pTM={ptm:.3f} ipTM={iptm:.3f} ranking={ranking:.3f}")
else:
    print(f"    {job}: pTM={ptm} ipTM={iptm} ranking={ranking}")
```

#### 2. 多进程Pickle错误
**问题**: multiprocessing无法pickle嵌套函数
```
AttributeError: Can't pickle local object '_run_parallel.<locals>.gpu_worker'
```

**修复**: 将worker函数移到模块级别
```python
# Before (nested function - cannot be pickled)
def _run_parallel(...):
    def gpu_worker(...):
        ...

# After (module-level function - can be pickled)
def _gpu_worker(...):
    ...

def _run_parallel(...):
    ...
```

#### 3. 相对路径错误
**问题**: 并行模式下使用相对路径和`cwd=json_path.parent`导致文件找不到
```
FileNotFoundError: [Errno 2] No such file or directory: 'AF3_results/multigpu_json_batch/multigpu_job1.json'
```

**修复**: 使用绝对路径，移除cwd参数
```python
# Before
result = subprocess.run(cmd, env=env, capture_output=True, text=True,
                       cwd=str(json_path.parent))

# After
json_path_abs = json_path.resolve()
output_dir_abs = output_dir.resolve()
cmd = [
    ...,
    '--json_path', str(json_path_abs),
    '--output_dir', str(output_dir_abs),
    ...
]
result = subprocess.run(cmd, env=env, capture_output=True, text=True)
```

### 功能验证

#### 全面测试（GPU 1）
1. ✅ 单链蛋白基本预测 - 28.6s, pLDDT=85.64
2. ✅ 同源二聚体预测 - 30.0s, pTM=0.840 ipTM=0.840
3. ✅ 蛋白+4个钙离子 - 28.9s, pTM=0.850 ipTM=0.800
4. ✅ 二聚体+4个钙离子 - 29.8s, pTM=0.890 ipTM=0.890
5. ✅ A3M格式MSA - 29.5s, 验证兼容性
6. ✅ 多样本生成 - 31.6s, 4个模型

#### 多GPU测试（GPU 1,2,3）
- ✅ 顺序模式: 3任务 ~90s
- ✅ 并行模式: 3任务 36s (2.5x speedup)
- ✅ GPU分配: 完美（每个GPU 1个任务）
- ✅ 成功率: 100% (3/3)

### 文档更新

#### SKILL.md
- ✅ 添加多GPU并行处理章节
- ✅ 添加性能基准测试数据
- ✅ 添加最佳实践建议
- ✅ 添加多GPU使用示例
- ✅ 添加注意事项和限制说明

#### 测试报告
- ✅ 单GPU全面测试报告: `AF3_full_test/test_summary.md`
- ✅ 多GPU测试报告: `AF3_full_test/multigpu_test_summary.md`

### 技术细节

#### 并行实现
- 使用`multiprocessing.Pool`实现进程池
- 每个GPU一个worker进程
- Round-robin任务分配策略
- 自动收集和汇总所有结果

#### 路径处理
- 所有路径使用`Path.resolve()`转换为绝对路径
- 避免工作目录改变导致的路径问题
- 支持相对路径和绝对路径输入

#### 错误处理
- 失败任务自动标记
- 输出最后300字符的stderr
- 统计成功/失败数量

### 兼容性
- ✅ Python 3.11+
- ✅ JAX with GPU support
- ✅ AlphaFold3 official release
- ✅ Linux (tested on Ubuntu)
- ✅ NVIDIA GPUs (RTX 4090 tested)

### 性能指标
- 平均单任务时间: ~30s (123 aa, 2 samples)
- GPU内存使用: 正常（无OOM）
- 并行效率: ~83% (3 GPUs)
- 加速比: 2.5x (3 GPUs vs 1 GPU)

### 已知限制
1. 单链蛋白不输出pTM/ipTM
2. JSON格式MSA需要AF3特定格式
3. MSA目录路径需要绝对路径或在正确目录下运行
4. 多GPU模式下需要足够的GPU内存

### 未来改进
- [ ] 支持RNA/DNA链
- [ ] 支持covalent bonds简洁语法
- [ ] 支持用户自定义CCD
- [ ] 自动最优GPU分配
- [ ] 进度条显示
- [ ] 失败任务自动重试

### 致谢
测试环境:
- GPU: NVIDIA GeForce RTX 4090 (49GB each)
- AlphaFold3: user-managed installation path
- Conda env: user-managed environment path
- Model weights: user-managed model directory
- Database: user-managed database directory
