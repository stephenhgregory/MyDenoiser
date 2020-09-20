#!/usr/bin/env bash
# Used to test myDenoiser

# Find and store the MyDenoiser repo path
MYDENOISER_REPO=$(find ~ -type d -wholename "*/MyDenoiser/keras_implementation" )

# Move into the MyDenoiser repo if it exists, otherwise exit with an error message
if [ "$MYDENOISER_REPO" == "\n" ] || [ -z "$MYDENOISER_REPO" ]
then
  echo "Could not find MyDenoiser repository. Clone that repo and try again!" && exit 1
else
  cd "$MYDENOISER_REPO" && echo "MyDenoiser repo found at $MYDENOISER_REPO"
fi

# Get the model type that the user wishes to test
printf "Which model do you want to test?\n"
printf "[1] Volume1-trained (all 3 models)\n"
printf "[2] Volume2-trained (all 3 models)\n"
printf "[3] subj1-trained (all 3 models)\n"
printf "[4] sub2-trained (all 3 models)\n"
printf "[5] Volume1-trained (1 all-noise model)\n"
printf "[6] Volume2-trained (1 all-noise model)\n"
printf "[7] subj1-trained (1 all-noise model)\n"
printf "[8] subj2-trained (1 all-noise model)\n"
printf "\n"
printf "Select a number: "
read -r MODEL_NUM

# Get the image directory that the user wishes to test on
printf "Which test data directory do you want to retest on?\n"
printf "[1] Volume1\n"
printf "[2] Volume2\n"
printf "[3] subj1\n"
printf "[4] subj2\n"
printf "\n"
printf "Select a number: "
read -r DATA_NUM

# [1] Volume1-trained (all 3 models)
if [ "$MODEL_NUM" == 1 ]
then
  TRAINED_DIR="Volume1"
  ALL_NOISE=0
# [2] Volume2-trained (all 3 models)
elif [ "$MODEL_NUM" == 2 ]
then
  TRAINED_DIR="Volume2"
  ALL_NOISE=0
# [3] subj1-trained (all 3 models)
elif [ "$MODEL_NUM" == 3 ]
then
  TRAINED_DIR="subj1"
  ALL_NOISE=0
# [4] subj2-trained (all 3 models)
elif [ "$MODEL_NUM" == 4 ]
then
  TRAINED_DIR="subj2"
  ALL_NOISE=0
# [5] Volume1-trained (1 all-noise model)
elif [ "$MODEL_NUM" == 5 ]
then
  TRAINED_DIR="Volume1"
  ALL_NOISE=1
# [6] Volume2-trained (1 all-noise model)
elif [ "$MODEL_NUM" == 6 ]
then
  TRAINED_DIR="Volume2"
  ALL_NOISE=1
# [7] subj1-trained (1 all-noise model)
elif [ "$MODEL_NUM" == 7 ]
then
  TRAINED_DIR="subj1"
  ALL_NOISE=1
# [8] subj2-trained (1 all-noise model)
elif [ "$MODEL_NUM" == 8 ]
then
  TRAINED_DIR="subj2"
  ALL_NOISE=1
fi

# [1] Using Volume1 for test data
if [ "$DATA_NUM" == 1 ]
then
  SET_DIR="data/Volume1"
# [2] Using Volume2 for test data
elif [ "$DATA_NUM" == 2 ]
then
  SET_DIR="data/Volume2"
# [3] Using subj1 for test data
elif [ "$DATA_NUM" == 3 ]
then
  SET_DIR="data/subj1"
# [4] Using subj2 for test data
elif [ "$DATA_NUM" == 4 ]
then
  SET_DIR="data/subj2"
fi

printf "Calling test.py for model trained on %s...\n" "$TRAINED_DIR"
python test.py \
    --single_denoiser="${ALL_NOISE}" \
    --set_dir="${SET_DIR}" \
    --train_data="data/${TRAINED_DIR}/train" \
    --result_dir="results/${TRAINED_DIR}Trained_results"
    --model_dir_all_noise="models/${TRAINED_DIR}Trained/MyDnCNN_all_noise/" \
    --model_dir_low_noise="models/${TRAINED_DIR}Trained/MyDnCNN_low_noise/" \
    --model_dir_medium_noise="models/${TRAINED_DIR}Trained/MyDnCNN_medium_noise/" \
    --model_dir_high_noise="models/${TRAINED_DIR}Trained/MyDnCNN_high_noise/"