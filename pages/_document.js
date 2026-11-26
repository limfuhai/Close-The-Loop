import { Head, Html, Main, NextScript } from "next/document";

export default function Document() {
  return (
    <Html lang="en">
      <Head>
        <meta name="theme-color" content="#000000" />
        <meta
          name="description"
          content="OpexAssistant: Your AI-Powered Desktop Companion"
        />
        {/* Combined CSP from main and staging branches */}
        <meta
          httpEquiv="Content-Security-Policy"
          content="
            default-src 'self';
            connect-src 'self'
              https://opexassistant.onrender.com
              https://opexassistant-staging.onrender.com
              https://tuner-efqc.onrender.com
              https://boundary.onrender.com
              https://*.vercel.app
              https://app.opexcg.com
              http://app.opexcg.com:8769
              https://*.clerk.accounts.dev
              https://*.clerk.com
              https://*.clerk.dev
              https://clerk-telemetry.com
              https://challenges.cloudflare.com
              https://clerk.xuanwo.ai
              https://*.xuanwo.ai
              https://api.stripe.com
              https://my-elasticsearch-project-fac5e4.es.ap-southeast-1.aws.elastic.cloud:443
              https://api.search.brave.com
              https://wiblnexxwcfipjbiqsso.supabase.co
              https://*.supabase.co
              https://*.supabase.in
              https://*.modal.run
              https://*.r2.cloudflarestorage.com
              http://localhost:3000
              http://localhost:8770;
            script-src 'self' 'unsafe-inline' 'unsafe-eval'
              https://*.clerk.accounts.dev
              https://*.clerk.com
              https://*.clerk.dev
              https://clerk-telemetry.com
              https://challenges.cloudflare.com
              https://clerk.xuanwo.ai
              https://js.stripe.com
              http://localhost:3000
              https://*.xuanwo.ai;
            img-src 'self' data: blob:
              https://img.clerk.com
              https://*.clerk.com
              https://*.clerk.dev
              https://tuner-efqc.onrender.com
              https://boundary.onrender.com
              https://wiblnexxwcfipjbiqsso.supabase.co
              https://*.supabase.co
              http://localhost:3000
              https://*.xuanwo.ai;
            worker-src 'self' blob:;
            style-src 'self' 'unsafe-inline';
          "
        />
        <meta httpEquiv="X-Content-Type-Options" content="nosniff" />
        {/* Remove the X-Frame-Options that's causing errors */}
        {/* <meta httpEquiv="X-Frame-Options" content="DENY" /> */}
      </Head>
      <body>
        {/* Add polyfill script before Main with __dirname support */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              if (typeof global === 'undefined') {
                window.global = window;
              }
              if (typeof __dirname === 'undefined') {
                window.__dirname = '';
              }
              if (typeof process === 'undefined') {
                window.process = { env: { NODE_ENV: '${process.env.NODE_ENV}' } };
              }
              if (typeof require === 'undefined') {
                window.require = function(module) {
                  console.warn('Polyfilled require called for: ' + module);
                  // Return empty objects/functions to prevent errors
                  return {};
                };
              }
            `,
          }}
        />
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
