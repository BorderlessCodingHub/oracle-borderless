import { ARCHITECTURE_MAP, type MapBox } from "../architectureMap";
import { boxMetric } from "../boxMetric";
import type { OpsOverview } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

export function ArchitectureMap({
  overview,
  selected,
  onSelect,
}: {
  overview: OpsOverview | null;
  selected: MapBox | null;
  onSelect: (box: MapBox) => void;
}) {
  return (
    <div className={styles.map}>
      {ARCHITECTURE_MAP.map((band) => (
        <section key={band.id} className={styles.band}>
          <h3 className={styles.bandTitle}>{band.title}</h3>
          <div className={styles.bandBoxes}>
            {band.boxes.map((box) => {
              const metric = boxMetric(box, overview);
              return (
                <button
                  key={box.id}
                  type="button"
                  onClick={() => onSelect(box)}
                  aria-pressed={selected?.id === box.id}
                  className={selected?.id === box.id ? styles.boxActive : styles.box}
                >
                  <span className={styles.boxLabel}>{box.label}</span>
                  {metric && <span className={styles.boxMetric}>{metric}</span>}
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
