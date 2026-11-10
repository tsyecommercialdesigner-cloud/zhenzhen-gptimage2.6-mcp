## ADDED Requirements

### Requirement: 格式与验证说明
系统 SHALL 向 Host 说明 SVG/GIF 格式、动态原件与静态预览的区别、渠道限制及各组合的验证状态，不把供应商文档支持表述为本项目实测通过。

#### Scenario: 查询新格式能力
- **WHEN** Host 查询 SVG 或 GIF 能力
- **THEN** 说明仅使用 t8-star、文生图限制及真实验证范围，并说明 GIF 预览可能是静态首帧、原件保留动画及尺寸不符的处理方式，SVG 原件保留矢量内容
