import ReactMarkdown from "react-markdown";
import type { Citation } from "../../../lib/types";
import type { ActivityItem } from "../../../hooks/useAskStream";
import { Logo } from "../../../components/Logo/Logo";
import { CitationsBlock } from "./CitationsBlock";
import { TurnTimeline } from "./TurnTimeline";
import { stripHtml, stripSourceMarkers } from "../../../lib/utils/text";
import { safeUrl } from "../../../lib/utils/safeUrl";
import styles from "../ChatPage.module.css";

type Props = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  streaming?: boolean;
  /** Linha do tempo do turno em andamento — só faz sentido com `streaming`. */
  activity?: ActivityItem[];
};

export function MessageBubble({ role, content, citations, streaming, activity }: Props) {
  if (role === "user") {
    return <div className={styles.userTurn}><div className={styles.userBubble}>{content}</div></div>;
  }
  return (
    <div className={styles.botTurn}>
      <Logo size={34} />
      <div className={styles.botBody}>
        {streaming && activity && <TurnTimeline activity={activity} />}
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
          {streaming && content && <span className={styles.cursor} />}
        </div>
        {citations && <CitationsBlock citations={citations} />}
      </div>
    </div>
  );
}
