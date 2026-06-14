import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type Props = {
  title: string;
  bullets: string[];
  photoFile: string;
  audioFile?: string;
};

const Bullet: React.FC<{ text: string; index: number }> = ({ text, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    fps,
    frame: frame - index * 12,
    config: { damping: 14, stiffness: 120 },
  });

  const opacity = interpolate(progress, [0, 1], [0, 1]);
  const translateX = interpolate(progress, [0, 1], [40, 0]);

  return (
    <div
      style={{
        opacity,
        transform: `translateX(${translateX}px)`,
        display: "flex",
        alignItems: "flex-start",
        gap: 16,
        marginBottom: 24,
      }}
    >
      <div
        style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: "#4fc3f7",
          marginTop: 10,
          flexShrink: 0,
        }}
      />
      <span style={{ fontSize: 36, color: "#fff", lineHeight: 1.5 }}>{text}</span>
    </div>
  );
};

export const Presentation: React.FC<Props> = ({
  title,
  bullets,
  photoFile,
  audioFile,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleProgress = spring({ fps, frame, config: { damping: 14 } });
  const titleOpacity = interpolate(titleProgress, [0, 1], [0, 1]);
  const titleY = interpolate(titleProgress, [0, 1], [-30, 0]);

  const photoProgress = spring({
    fps,
    frame: frame - 5,
    config: { damping: 14 },
  });
  const photoScale = interpolate(photoProgress, [0, 1], [0.8, 1]);
  const photoOpacity = interpolate(photoProgress, [0, 1], [0, 1]);

  return (
    <AbsoluteFill
      style={{
        background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
        display: "flex",
        flexDirection: "row",
        padding: 60,
        gap: 60,
      }}
    >
      {audioFile && <Audio src={staticFile(audioFile)} />}

      {/* 左: 顔写真 */}
      <div
        style={{
          width: 380,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 24,
        }}
      >
        <div
          style={{
            width: 300,
            height: 300,
            borderRadius: "50%",
            overflow: "hidden",
            border: "4px solid #4fc3f7",
            boxShadow: "0 0 40px rgba(79,195,247,0.4)",
            opacity: photoOpacity,
            transform: `scale(${photoScale})`,
          }}
        >
          <Img
            src={staticFile(photoFile)}
            style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "top" }}
          />
        </div>
      </div>

      {/* 右: スライドコンテンツ */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        {/* タイトル */}
        <div
          style={{
            opacity: titleOpacity,
            transform: `translateY(${titleY}px)`,
            marginBottom: 48,
          }}
        >
          <div
            style={{
              width: 60,
              height: 4,
              background: "#4fc3f7",
              borderRadius: 2,
              marginBottom: 20,
            }}
          />
          <h1
            style={{
              fontSize: 52,
              color: "#fff",
              margin: 0,
              fontWeight: 700,
              lineHeight: 1.3,
            }}
          >
            {title}
          </h1>
        </div>

        {/* 箇条書き */}
        <div>
          {bullets.map((b, i) => (
            <Bullet key={i} text={b} index={i + 2} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
