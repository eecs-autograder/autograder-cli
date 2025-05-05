if [ -z "$1" ]; then
    echo "Usage: $0 test_name"
    exit 1
fi

test_dir=$(dirname "$(realpath $0)")/roundtrip/$1
[[ $test_dir == *.test ]] || test_dir+=.test
echo $test_dir

if [ -d $test_dir ]; then
    echo This test case directory already exists
    exit 1
fi
mkdir -p $test_dir

proj_uuid=$(python -c "import uuid; print(uuid.uuid4().hex)")

cat > $test_dir/agproject.create.yml <<- EOM
project:
  name: Test Project $proj_uuid
  timezone: America/Chicago
  course:
    name: Test Course
    semester: Summer
    year: 2014
  settings:
EOM

cp $test_dir/agproject.create.yml $test_dir/agproject.update.yml
cp $test_dir/agproject.create.yml $test_dir/agproject.create.expected.yml
cp $test_dir/agproject.update.yml $test_dir/agproject.update.expected.yml

echo "relative" | cat > $test_dir/deadline_cutoff_preference
