/** @type {import('next').NextConfig} */
const nextConfig = {
  // firebase-admin is optional; don't let the bundler choke when it's absent.
  serverExternalPackages: ["firebase-admin"],
};

export default nextConfig;
