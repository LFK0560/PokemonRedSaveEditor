# 口袋妖怪红存档修改器

Windows x64 离线存档编辑器。可编辑随身队伍、12 个精灵箱、背包和 PC 道具。已验证的简体中文红版还支持原版地图和单个事件复位。

v1.1.0-beta.1 开放国际版红、蓝、黄的核心存档编辑，使用实际数据表识别英文、法文、德文、意大利文和西班牙文 ROM。可在 [测试版发行页](https://github.com/LFK0560/PokemonRedSaveEditor/releases/tag/v1.1.0-beta.1) 下载并反馈兼容性问题。 [国际版布局与测试范围](docs/国际版兼容.md)

## 快速开始

1. 在 [国际版兼容测试版](https://github.com/LFK0560/PokemonRedSaveEditor/releases/tag/v1.1.0-beta.1) 下载 `PokemonRedSaveEditor_Windows_x64.zip`。完整解压后双击 `PokemonRedSaveEditor.exe`。原有中文版发行包保留在 [v1.0.0](https://github.com/LFK0560/PokemonRedSaveEditor/releases/tag/v1.0.0)。
2. 点「选择 ROM」，选取与存档对应的本地 ROM。点「导入存档」，选取游戏内保存生成的 `.srm`。测试版也接受 `.sav`。
3. 在「队伍与精灵箱」或「道具」中应用编辑，或在「地图与事件」中点选目标并复位。点「保存」或「另存为」把改动写入文件。

## 注意事项

- v1.0.0 适配 [使用说明所列 SHA-256](docs/使用说明.md#选择-rom-和存档) 对应的简体中文红版。测试版已开放国际版红、蓝、黄。ROM 与 32 KiB SRAM 存档由玩家自行提供。
- 写入前请关闭正在使用该存档的模拟器，避免模拟器随后把旧内容写回。初次编辑可用「另存为」生成一份副本。
- 每次成功导入都会把原档放进存档旁的 `备份/YYYY-MM-DD/`。当天同名备份依次添加 `_2`、`_3` 等编号。覆盖保存前另有一份 `_覆盖前` 备份，可从「查看备份」找到。
- 仅可复位已核实能独立恢复的目标。道馆馆主和会影响剧情通路的事件在地图上显示禁用原因。

## 文档

- [完整使用说明](docs/使用说明.md)
- [国际版存档布局与兼容测试](docs/国际版兼容.md)
- [开发路线图与当前局限](docs/开发路线图.md)
- [Windows 源码构建与回归命令](docs/构建.md)
- [事件覆盖与禁用规则](docs/事件覆盖.md) · [逐项事件索引 CSV](docs/事件索引.csv)
- [Windows 与模拟器验收记录](docs/验收.md)

## 许可证

本项目源码采用 [MIT 许可证](LICENSE)。Windows 发行包中的 Qt、PySide6 等依赖按各自的许可证分发。 [第三方组件及许可证](docs/第三方组件.md)
