import { Html, Head, Main, NextScript } from "next/document";

export default function Document() {
  return (
    <Html>
      <Head />
      <body>
        {/*
          Inline script runs synchronously before React hydration.
          It reads the stored theme preference and applies the class
          to <html> immediately to prevent a flash of the wrong theme.
        */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function(){
                try {
                  var t = localStorage.getItem('or-theme') || 'dark';
                  document.documentElement.classList.add(t);
                  if (t === 'dark') document.documentElement.classList.remove('light');
                  else              document.documentElement.classList.remove('dark');
                } catch(e) {
                  document.documentElement.classList.add('dark');
                }
              })();
            `,
          }}
        />
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
