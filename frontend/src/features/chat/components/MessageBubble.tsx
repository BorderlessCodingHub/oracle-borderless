import ReactMarkdown from "react-markdown";
import type { Citation } from "../../../lib/types";
import { Logo } from "../../../components/Logo/Logo";
import { CitationsBlock } from "./CitationsBlock";
import { stripHtml, stripSourceMarkers } from "../../../lib/utils/text";
import { safeUrl } from "../../../lib/utils/safeUrl";
import styles from "../ChatPage.module.css";

type Props = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  streaming?: boolean;
};

export function MessageBubble({ role, content, citations, streaming }: Props) {
  if (role === "user") {
    return <div className={styles.userTurn}><div className={styles.userBubble}>{content}</div></div>;
  }
  return (
    <div className={styles.botTurn}>
      <Logo size={34} />
      <div className={styles.botBody}>
        <div className={styles.botText}>
          <ReactMarkdown
            components={{
              a: ({ href, children }) => {
                const safe = href ? safeUrl(href) : null;
                return safe ? (
                  <a href={safe} target="_blank" rel="noreferrer">{children}</a>
                ) : (
                  <>{children}</>
                );
              },
              img: ({ alt }) => <>{alt ?? ""}</>,
            }}
          >
            {stripHtml(stripSourceMarkers(content))}
          </ReactMarkdown>
          {streaming && <span className={styles.cursor} />}
        </div>
        {citations && <CitationsBlock citations={citations} />}
      </div>
    </div>
  );
}
