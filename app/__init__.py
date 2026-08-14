"""
rusin-note - 极简在线笔记服务 (支持匿名公开笔记 /world/ 和私有用户笔记 /user/)
- 公开笔记无需登录，直接访问 /world/<id> 即可编辑
- 私有笔记需注册登录，路径 /user/<username>/<note_id>
- 顶部导航栏，登录/注册/登出
- 密码强度要求可配置
- 支持 /<剪贴板名称> 短链接自动重定向到公开笔记 /world/<剪贴板名称>
- 支持 /<剪贴板名称>.md 直接渲染为 Markdown；其他扩展名 (.html/.exe/.pdf 等) 一律 404
- 保留关键词（login/logout 等）禁止注册为用户名
- 统计页面 /count
- 免责声明 /disclaimer，支持Markdown渲染
- Cookie使用SHA-256哈希存储，会话支持超时清除
- 支持将公开笔记渲染为 Markdown（只读）：/world/<id>/md 或 /world/<id>.md
- 支持将私有笔记渲染为 Markdown（仅本人）：/user/<用户名>/<笔记ID>/md 或 /user/<用户名>/<笔记ID>.md
- 支持将分享渲染为 Markdown（只读）：/share/<token>/md 或 /share/<token>.md
- 分享功能：私有笔记可生成分享链接 /share/<token>（长度与字符集可配置，支持只读/可编辑）
- 分享管理：/user/<用户名>/shares/（创建/删除/查看次数）
- 犇犇动态：/benben（登录可发布，未登录只读；每条显示用户名+时间，支持 Markdown/LaTeX，安全清洗防 XSS，每页 50 条分批加载）
- LaTeX 公式渲染：Markdown 只读页面支持 $...$ / $$...$$（KaTeX 洛谷同款，可配置开关与 CDN）
- 暗色模式：所有页面支持切换（localStorage 记忆 + 跟随系统偏好，导航栏按钮切换）
- XSS防护：使用bleach清洗Markdown渲染后的HTML
- GET请求独立限流（45次/分钟）
- 编辑区 Tab 键插入 4 个空格
"""
