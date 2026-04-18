I was a bit worried about the NAS server's slowness
I reused my following PC for Ubuntu server
  
Machine

  - Hostname: commoncreed-server
  - CPU: AMD Ryzen 5 3600X 6-Core
  - RAM: 16 GB
  - GPU: NVIDIA GeForce RTX 2070 SUPER (8 GB VRAM), driver 580.126.09
  - Disk: 246 GB (224 GB free)
  - OS: Ubuntu 24.04.4 LTS

  Network

  - LAN IP: 192.168.29.237 (Wi-Fi, via Deco)
  - Tailscale IP: 100.72.251.52
  - Tailscale DNS: commoncreed-server.tail47ec78.ts.net
  - Public IP: 2405:201:68:7809:e7a:15ff:fe7a:8c8 (IPv6)

  Access

  - SSH (LAN): ssh vishalan@192.168.29.237
  - SSH (anywhere): ssh vishalan@100.72.251.52
  - Portainer (LAN): https://192.168.29.237:9443
  - Portainer (anywhere, valid TLS): https://commoncreed-server.tail47ec78.ts.net:9443

  Firewall (UFW)

  - SSH allowed from LAN (192.168.29.0/24) and Tailscale (100.64.0.0/10)
  - Portainer allowed from Tailscale only
  - Everything else denied inbound

  Software

  - Docker 29.4.0 + Compose v2 + NVIDIA Container Toolkit
  - Portainer CE (LTS) — restart: always
  - Tailscale 1.96.4 — enabled on boot

SSH Key added already 


1. Move this entire setup to this server
2. help me with a step by step guide to update the Youtube, Gmail, Facebook and all the redirect urls
3. Ensure all the configs and external apps needed to be updated helped to me with a proper walkthrough
4. Remove the setup from existing server once the new server is up and running end to end