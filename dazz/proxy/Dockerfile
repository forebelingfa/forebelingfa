# Use the official lightweight V2Ray image
FROM v2fly/v2fly-core:latest

# Expose the internal SOCKS5 proxy port
EXPOSE 10808

# The command to run V2Ray. It will look for a config file
# that docker-compose will provide at runtime.
CMD ["run", "-config", "/etc/v2ray/config.json"]