# Base image minimaliste Debian avec outils de compilation
FROM debian:bullseye-slim

# Mise à jour et installation des dépendances (GCC, Make, libcurl)
RUN apt-get update && \
    apt-get install -y gcc make libcurl4-openssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Définir le répertoire de travail
WORKDIR /app

# Copier le code source
COPY stt_client.c .

# Compiler le client STT en C
RUN gcc -o stt_client stt_client.c -lcurl

# Lancer la boucle STT
CMD ["./stt_client"]
