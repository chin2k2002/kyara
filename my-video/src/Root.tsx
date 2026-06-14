import { Composition } from "remotion";
import { HelloWorld } from "./HelloWorld";
import { Presentation } from "./Presentation";
import "./style.css";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="HelloWorld"
        component={HelloWorld}
        durationInFrames={150}
        fps={30}
        width={1280}
        height={720}
        defaultProps={{
          titleText: "Welcome to Remotion",
          titleColor: "#000000",
        }}
      />
      <Composition
        id="Presentation"
        component={Presentation}
        durationInFrames={300}
        fps={30}
        width={1280}
        height={720}
        defaultProps={{
          title: "本日のプレゼンテーション",
          bullets: [
            "自己紹介",
            "今日のテーマ",
            "まとめ",
          ],
          photoFile: "photo.jpg",
          audioFile: "speech.wav",
        }}
      />
    </>
  );
};
