import os
import json
from pathlib import Path
import shutil
from datetime import datetime
import yaml

class SampleExtractor:
    def __init__(self, source_folders, target_dir="samples"):
        self.source_folders = source_folders
        self.target_dir = Path(target_dir)
        
        # Read from config.yaml directly to avoid magic strings
        with open("config/config.yaml", 'r') as f:
            config = yaml.safe_load(f)
            
        paths = config.get('paths', {})
        
        self.pred_dir = self.target_dir / paths.get('predictions_dir', 'predictions')
        self.rev_dir = self.target_dir / paths.get('reviews_dir', 'reviews')
        self.img_dir = self.target_dir / paths.get('images_dir', 'images')
        
        # Source images come from the main live data directory
        self.image_source_dir = Path(paths.get('base_dir', 'data')) / paths.get('images_dir', 'images')
        
        for d in [self.pred_dir, self.rev_dir, self.img_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def extract(self):
        count = 0
        for folder in self.source_folders:
            folder_path = Path(folder)
            if not folder_path.exists():
                continue
                
            for review_file in folder_path.glob("review_*.json"):
                with open(review_file, 'r') as f:
                    try:
                        data = json.load(f)
                    except:
                        continue
                        
                analysis = data.get('analysis', {})
                pred_content = data.get('prediction', {}).get('content', {})
                
                if not isinstance(analysis, dict): continue
                
                score = analysis.get('evaluation_score', 100)
                result = analysis.get('tp_sl_result', 'NEITHER')
                timestamp = pred_content.get('timestamp')
                symbol = pred_content.get('config_context', {}).get('symbol', 'BTCUSDT')
                
                if result == 'SL_HIT' or score <= 25:
                    source_pred_file = data.get('prediction', {}).get('source', '')
                    pred_path = folder_path / source_pred_file
                    
                    if timestamp and pred_path.exists():
                        try:
                            dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
                            for tf in ['15m', '1h']:
                                img_filename = f"{symbol}_{tf}_{dt.strftime('%Y%m%d_%H%M%S')}Z_chart.png"
                                source_img_path = self.image_source_dir / img_filename
                                target_img_path = self.img_dir / img_filename
                                
                                if source_img_path.exists():
                                    shutil.move(str(source_img_path), str(target_img_path))
                        except ValueError:
                            pass

                        target_rev = self.rev_dir / review_file.name
                        target_pred = self.pred_dir / source_pred_file
                        
                        shutil.move(str(review_file), str(target_rev))
                        shutil.move(str(pred_path), str(target_pred))
                        count += 1

        print(f"Extraction complete. Moved {count} sample(s) to {self.target_dir}/")

if __name__ == "__main__":
    sources = ['data/archive_training_v1', 'data/archive_training_v1.1'] # Add paths here
    extractor = SampleExtractor(sources)
    extractor.extract()
