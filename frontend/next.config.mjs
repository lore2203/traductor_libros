/** El navegador llama a /api/* en el mismo origen; Next lo reenvía al backend (sin CORS). */
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
// Debe coincidir con MAX_UPLOAD_MB del backend: el proxy de Next corta los cuerpos a 10 MB por defecto
const MAX_UPLOAD_MB = process.env.MAX_UPLOAD_MB || "200";

const nextConfig = {
  output: "standalone",
  experimental: {
    proxyClientMaxBodySize: `${MAX_UPLOAD_MB}mb`,
    proxyTimeout: 300_000, // subir un libro grande puede tardar
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
