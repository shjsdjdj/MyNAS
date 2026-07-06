# MyNAS Cloudflare Tunnel 模板

这里只提供配置模板，不会登录 Cloudflare、创建 Tunnel、修改 DNS 或保存 Token。

## 使用前

1. 将域名接入 Cloudflare。
2. 安装 Windows 版 `cloudflared`。
3. 在 Cloudflare Zero Trust 创建命名 Tunnel，并取得 Tunnel UUID 与凭据 JSON。
4. 复制 `config.example.yml` 到 `%USERPROFILE%\.cloudflared\config.yml`，替换 UUID、Windows 用户名和域名。
5. 在项目 `.env` 中设置 `MYNAS_PUBLIC_HOST=mynas.example.com`。
6. 远程 HTTPS 使用时，将后端环境变量设为 `MYNAS_COOKIE_SECURE=true`。

验证并运行：

```powershell
cloudflared tunnel ingress validate
cloudflared tunnel ingress rule https://mynas.example.com
cloudflared tunnel run <TUNNEL-NAME>
```

生产映射关系：`https://mynas.example.com` → `http://127.0.0.1:8000`。先运行 `npm run build`，由 FastAPI 提供构建后的 Vue SPA；不要把 Vite 开发服务器暴露到 Tunnel。

安全建议：在 Cloudflare Zero Trust 中为该域名创建 Self-hosted Access 应用。MyNAS 自身的 JWT 登录仍然保留，形成两层认证。不要把 `credentials-file` 或 Tunnel Token 提交到项目目录。

官方资料：

- https://developers.cloudflare.com/tunnel/
- https://developers.cloudflare.com/tunnel/advanced/local-management/configuration-file/
- https://developers.cloudflare.com/tunnel/advanced/local-management/as-a-service/windows/
