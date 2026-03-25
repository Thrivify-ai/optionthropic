import Head from "next/head";

import "../styles/globals.css";

export default function App({ Component, pageProps }) {
  return (
    <>
      <Head>
        <title>Optionthropic - Options Analytics</title>
        <meta
          name="description"
          content="Institutional-grade derivatives analytics for NIFTY, BANKNIFTY, and SENSEX"
        />
      </Head>
      <Component {...pageProps} />
    </>
  );
}
